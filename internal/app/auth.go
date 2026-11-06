package app

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"golang.org/x/crypto/pbkdf2"
	"golang.org/x/crypto/scrypt"
)

const sessionCookie = "celltracker_session"

type sessionPayload struct {
	Username    string `json:"u"`
	DisplayName string `json:"d"`
	UserID      int64  `json:"i"`
	Expires     int64  `json:"e"`
}

type Auth struct {
	cfg    *Config
	store  *Store
	secret []byte
}

func NewAuth(cfg *Config, store *Store) (*Auth, error) {
	if !cfg.AuthEnabled {
		return &Auth{cfg: cfg, store: store}, nil
	}
	secret, err := loadOrCreateSecret(cfg)
	if err != nil {
		return nil, err
	}
	return &Auth{cfg: cfg, store: store, secret: secret}, nil
}

func loadOrCreateSecret(cfg *Config) ([]byte, error) {
	path := filepath.Join(filepath.Dir(cfg.DBPath), ".secret_key")
	if data, err := os.ReadFile(path); err == nil {
		value := strings.TrimSpace(string(data))
		if value != "" {
			return []byte(value), nil
		}
	}
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return nil, err
	}
	value := hex.EncodeToString(buf)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	if err := os.WriteFile(path, []byte(value), 0o600); err != nil {
		return nil, err
	}
	return []byte(value), nil
}

func (a *Auth) sign(payload sessionPayload) string {
	raw, _ := json.Marshal(payload)
	encoded := base64.RawURLEncoding.EncodeToString(raw)
	mac := hmac.New(sha256.New, a.secret)
	mac.Write([]byte(encoded))
	signature := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	return encoded + "." + signature
}

func (a *Auth) verify(value string) (sessionPayload, bool) {
	var payload sessionPayload
	parts := strings.Split(value, ".")
	if len(parts) != 2 {
		return payload, false
	}
	mac := hmac.New(sha256.New, a.secret)
	mac.Write([]byte(parts[0]))
	expected := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	if subtle.ConstantTimeCompare([]byte(expected), []byte(parts[1])) != 1 {
		return payload, false
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return payload, false
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return payload, false
	}
	if payload.Expires < time.Now().Unix() {
		return payload, false
	}
	return payload, true
}

func (a *Auth) Current(r *http.Request) (string, string) {
	if !a.cfg.AuthEnabled {
		return "local", "本地用户"
	}
	cookie, err := r.Cookie(sessionCookie)
	if err != nil {
		return "", ""
	}
	payload, ok := a.verify(cookie.Value)
	if !ok {
		return "", ""
	}
	return payload.Username, payload.DisplayName
}

func (a *Auth) Guard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !a.cfg.AuthEnabled {
			next.ServeHTTP(w, r)
			return
		}
		path := r.URL.Path
		if !strings.HasPrefix(path, "/api/") ||
			strings.HasPrefix(path, "/api/auth/") ||
			path == "/api/healthz" {
			next.ServeHTTP(w, r)
			return
		}
		if username, _ := a.Current(r); username != "" {
			next.ServeHTTP(w, r)
			return
		}
		writeJSON(w, http.StatusUnauthorized, map[string]any{
			"error": map[string]any{"code": "unauthorized", "message": "请先登录"},
		})
	})
}

func (a *Auth) Bootstrap(ctx context.Context) error {
	if !a.cfg.AuthEnabled {
		return nil
	}
	var count int
	if err := a.store.DB().QueryRowContext(ctx, `SELECT COUNT(*) FROM users`).Scan(&count); err != nil {
		return err
	}
	if count > 0 {
		return nil
	}
	_, err := createUser(ctx, a.store.DB(), a.cfg.BootstrapUser, a.cfg.BootstrapPass, "管理员")
	if err != nil {
		return err
	}
	fmt.Printf("[auth] 已创建默认账号 %s / %s，请登录后立即修改密码\n", a.cfg.BootstrapUser, a.cfg.BootstrapPass)
	return nil
}

func hashPassword(password string) (string, error) {
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	saltText := hex.EncodeToString(salt)
	iterations := 600000
	derived := pbkdf2.Key([]byte(password), []byte(saltText), iterations, 32, sha256.New)
	return fmt.Sprintf("pbkdf2:sha256:%d$%s$%s", iterations, saltText, hex.EncodeToString(derived)), nil
}

func checkPassword(encoded, password string) bool {
	parts := strings.Split(encoded, "$")
	if len(parts) != 3 {
		return false
	}
	method := strings.Split(parts[0], ":")
	switch method[0] {
	case "pbkdf2":
		if len(method) < 2 || method[1] != "sha256" {
			return false
		}
		iterations := 600000
		if len(method) >= 3 {
			if value, err := strconv.Atoi(method[2]); err == nil {
				iterations = value
			}
		}
		expected, err := hex.DecodeString(parts[2])
		if err != nil {
			return false
		}
		derived := pbkdf2.Key([]byte(password), []byte(parts[1]), iterations, len(expected), sha256.New)
		return subtle.ConstantTimeCompare(expected, derived) == 1
	case "scrypt":
		if len(method) < 4 {
			return false
		}
		n, _ := strconv.Atoi(method[1])
		r, _ := strconv.Atoi(method[2])
		p, _ := strconv.Atoi(method[3])
		if n <= 1 || r <= 0 || p <= 0 {
			return false
		}
		expected, err := hex.DecodeString(parts[2])
		if err != nil {
			return false
		}
		derived, err := scrypt.Key([]byte(password), []byte(parts[1]), n, r, p, len(expected))
		if err != nil {
			return false
		}
		return subtle.ConstantTimeCompare(expected, derived) == 1
	}
	return false
}

func createUser(ctx context.Context, q Querier, username, password, displayName string) (Row, error) {
	username = strings.TrimSpace(username)
	if username == "" || len([]rune(username)) > 60 {
		return nil, validationError("用户名不能为空且不超过 60 字符")
	}
	if len(password) < 6 {
		return nil, validationError("密码至少 6 位")
	}
	existing, err := queryOne(ctx, q, `SELECT id FROM users WHERE username = ?`, username)
	if err != nil {
		return nil, err
	}
	if existing != nil {
		return nil, validationError(fmt.Sprintf("用户「%s」已存在", username))
	}
	hash, err := hashPassword(password)
	if err != nil {
		return nil, err
	}
	if displayName == "" {
		displayName = username
	}
	result, err := q.ExecContext(ctx,
		`INSERT INTO users (username, password_hash, display_name, is_active, created_at)
		 VALUES (?,?,?,1,?)`,
		username, hash, displayName, time.Now().Format("2006-01-02T15:04:05"))
	if err != nil {
		return nil, err
	}
	id, _ := result.LastInsertId()
	return Row{"id": id, "username": username, "display_name": displayName}, nil
}

func setPassword(ctx context.Context, q Querier, username, password string) (Row, error) {
	username = strings.TrimSpace(username)
	if len(password) < 6 {
		return nil, validationError("密码至少 6 位")
	}
	row, err := queryOne(ctx, q, `SELECT id FROM users WHERE username = ?`, username)
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, validationError(fmt.Sprintf("用户「%s」不存在", username))
	}
	hash, err := hashPassword(password)
	if err != nil {
		return nil, err
	}
	if _, err := q.ExecContext(ctx, `UPDATE users SET password_hash = ? WHERE id = ?`, hash, rowInt(row, "id")); err != nil {
		return nil, err
	}
	return Row{"id": rowInt(row, "id"), "username": username}, nil
}

func listUsers(ctx context.Context, q Querier) ([]Row, error) {
	return queryMaps(ctx, q,
		`SELECT id, username, display_name, is_active, created_at FROM users ORDER BY username`)
}

func authenticate(ctx context.Context, q Querier, username, password string) (Row, error) {
	row, err := queryOne(ctx, q,
		`SELECT id, username, password_hash, display_name, is_active FROM users WHERE username = ?`,
		strings.TrimSpace(username))
	if err != nil {
		return nil, err
	}
	if row == nil || !checkPassword(rowString(row, "password_hash"), password) {
		return nil, &APIError{Status: http.StatusUnauthorized, Code: "invalid_credentials", Message: "用户名或密码不正确"}
	}
	if !rowBool(row, "is_active") {
		return nil, &APIError{Status: http.StatusForbidden, Code: "user_disabled", Message: "该账号已被禁用"}
	}
	return row, nil
}

func (a *Auth) HandleStatus(w http.ResponseWriter, r *http.Request) {
	username, displayName := a.Current(r)
	authenticated := !a.cfg.AuthEnabled || username != ""
	writeJSON(w, http.StatusOK, map[string]any{
		"enabled":       a.cfg.AuthEnabled,
		"authenticated": authenticated,
		"username":      nullableText(username),
		"display_name":  nullableText(displayName),
	})
}

func (a *Auth) HandleMe(w http.ResponseWriter, r *http.Request) {
	username, displayName := a.Current(r)
	if !a.cfg.AuthEnabled {
		writeJSON(w, http.StatusOK, map[string]any{
			"authenticated": true, "username": "local", "display_name": "本地用户", "auth_enabled": false,
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"authenticated": username != "",
		"username":      nullableText(username),
		"display_name":  nullableText(displayName),
		"auth_enabled":  true,
	})
}

func (a *Auth) HandleLogin(w http.ResponseWriter, r *http.Request) {
	if !a.cfg.AuthEnabled {
		writeError(w, &APIError{Status: http.StatusBadRequest, Code: "auth_disabled", Message: "当前未启用登录认证"})
		return
	}
	payload, err := readBodyAny(r)
	if err != nil {
		writeError(w, err)
		return
	}
	username := strings.TrimSpace(asString(payload["username"]))
	password := asString(payload["password"])
	if username == "" || password == "" {
		writeError(w, validationError("请输入用户名和密码"))
		return
	}
	user, err := authenticate(r.Context(), a.store.DB(), username, password)
	if err != nil {
		writeError(w, err)
		return
	}
	session := sessionPayload{
		Username:    rowString(user, "username"),
		DisplayName: rowString(user, "display_name"),
		UserID:      rowInt(user, "id"),
		Expires:     time.Now().AddDate(0, 0, a.cfg.SessionDays).Unix(),
	}
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookie,
		Value:    a.sign(session),
		Path:     "/",
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
		MaxAge:   a.cfg.SessionDays * 86400,
	})
	writeJSON(w, http.StatusOK, map[string]any{
		"authenticated": true,
		"id":            rowInt(user, "id"),
		"username":      rowString(user, "username"),
		"display_name":  rowString(user, "display_name"),
	})
}

func (a *Auth) HandleLogout(w http.ResponseWriter, r *http.Request) {
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookie,
		Value:    "",
		Path:     "/",
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
		MaxAge:   -1,
	})
	writeJSON(w, http.StatusOK, map[string]any{"authenticated": false})
}

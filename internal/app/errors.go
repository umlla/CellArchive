package app

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
)

type APIError struct {
	Status  int
	Code    string
	Message string
	Details any
}

func (e *APIError) Error() string { return e.Message }

func (e *APIError) body() map[string]any {
	payload := map[string]any{"code": e.Code, "message": e.Message}
	if e.Details != nil {
		payload["details"] = e.Details
	}
	return map[string]any{"error": payload}
}

func validationError(message string) *APIError {
	return &APIError{Status: http.StatusBadRequest, Code: "validation_error", Message: message}
}

func notFoundError(message string) *APIError {
	return &APIError{Status: http.StatusNotFound, Code: "not_found", Message: message}
}

func conflictError(message string) *APIError {
	return &APIError{Status: http.StatusConflict, Code: "conflict", Message: message}
}

func unauthorizedError(message string) *APIError {
	return &APIError{Status: http.StatusUnauthorized, Code: "unauthorized", Message: message}
}

func newJSONEncoder(w io.Writer) *json.Encoder {
	encoder := json.NewEncoder(w)
	encoder.SetEscapeHTML(false)
	return encoder
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = newJSONEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, err error) {
	var apiErr *APIError
	if errors.As(err, &apiErr) {
		writeJSON(w, apiErr.Status, apiErr.body())
		return
	}
	message := err.Error()
	lower := strings.ToLower(message)
	if strings.Contains(lower, "unique constraint") {
		code := "conflict"
		text := "名称已存在，请换一个名称"
		writeJSON(w, http.StatusConflict, map[string]any{
			"error": map[string]any{"code": code, "message": text},
		})
		return
	}
	writeJSON(w, http.StatusInternalServerError, map[string]any{
		"error": map[string]any{
			"code":    "internal_error",
			"message": fmt.Sprintf("服务器内部错误：%s", message),
		},
	})
}

package main

import (
	"bufio"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"celltracker/internal/app"
)

func main() {
	os.Exit(run())
}

func run() int {
	var (
		configPath  string
		host        string
		port        int
		dataDir     string
		noBrowser   bool
		showVersion bool
	)
	flag.StringVar(&configPath, "config", "", "配置文件路径（默认查找 data/config.json 或程序目录）")
	flag.StringVar(&host, "host", "", "监听地址，例如 127.0.0.1 或 0.0.0.0")
	flag.IntVar(&port, "port", 0, "监听端口（默认 18600）")
	flag.StringVar(&dataDir, "data-dir", "", "数据目录（数据库、备份、日志都放在这里）")
	flag.BoolVar(&noBrowser, "no-browser", false, "启动后不自动打开浏览器")
	flag.BoolVar(&showVersion, "version", false, "显示版本号")
	flag.Parse()

	if showVersion {
		fmt.Printf("CellTracker %s (%s/%s)\n", app.AppVersion, runtime.GOOS, runtime.GOARCH)
		return 0
	}

	cfg, err := app.LoadConfig(configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "读取配置失败：%v\n", err)
		pause()
		return 1
	}
	if dataDir != "" {
		app.ApplyDataDir(cfg, dataDir)
	}
	if host != "" {
		cfg.Host = host
	}
	if port != 0 {
		cfg.Port = port
	}
	if noBrowser {
		cfg.OpenBrowser = false
	}

	setupLogging(cfg)
	log.Printf("CellTracker %s 启动，数据库：%s", app.AppVersion, cfg.DBPath)

	if _, err := app.EnsureDatabase(cfg); err != nil {
		log.Printf("初始化数据库失败：%v", err)
		pause()
		return 1
	}
	store, err := app.OpenStore(cfg.DBPath)
	if err != nil {
		log.Printf("打开数据库失败：%v", err)
		pause()
		return 1
	}
	defer store.Close()
	application, err := app.New(cfg, store)
	if err != nil {
		log.Printf("初始化应用失败：%v", err)
		pause()
		return 1
	}

	localURL := fmt.Sprintf("http://127.0.0.1:%d/", cfg.Port)
	if portInUse(cfg.Host, cfg.Port) {
		if existingCellTracker(cfg.Port) {
			printBanner(cfg, localURL, true)
			if cfg.OpenBrowser {
				openBrowser(cfg, localURL)
			}
			pause()
			return 0
		}
		fmt.Printf("端口 %d 已被其他程序占用，CellTracker 无法启动。\n", cfg.Port)
		fmt.Println("请修改 config.json 的 port（例如 18601）后重试。")
		pause()
		return 1
	}

	shutdownCh := make(chan struct{})
	var shutdownOnce sync.Once
	application.SetShutdown(func() {
		shutdownOnce.Do(func() { close(shutdownCh) })
	})

	server := &http.Server{
		Addr:              net.JoinHostPort(cfg.Host, strconv.Itoa(cfg.Port)),
		Handler:           application.Handler(),
		ReadHeaderTimeout: 15 * time.Second,
		IdleTimeout:       120 * time.Second,
	}
	printBanner(cfg, localURL, false)
	if cfg.OpenBrowser {
		go func() {
			if waitForHealth(cfg.Port, 6*time.Second) {
				openBrowser(cfg, localURL)
			}
		}()
	}

	errCh := make(chan error, 1)
	go func() {
		errCh <- server.ListenAndServe()
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	select {
	case err := <-errCh:
		if err != nil && err != http.ErrServerClosed {
			log.Printf("服务启动失败：%v", err)
			pause()
			return 1
		}
		return 0
	case <-stop:
		log.Println("正在停止服务…")
	case <-shutdownCh:
		log.Println("收到退出请求，正在停止服务…")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = server.Shutdown(ctx)
	return 0
}

func setupLogging(cfg *app.Config) {
	_ = cfg.EnsureDirs()
	path := filepath.Join(filepath.Dir(cfg.DBPath), "celltracker.log")
	file, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		log.SetOutput(os.Stdout)
		return
	}
	log.SetOutput(io.MultiWriter(os.Stdout, file))
	log.SetFlags(log.LstdFlags)
}

func printBanner(cfg *app.Config, localURL string, alreadyRunning bool) {
	fmt.Println(strings.Repeat("=", 62))
	fmt.Printf(" 🧬 CellTracker %s\n", app.AppVersion)
	fmt.Printf(" 数据库：%s\n", cfg.DBPath)
	if alreadyRunning {
		fmt.Printf(" CellTracker 已经在运行：%s\n", localURL)
		fmt.Println(" 请直接用浏览器打开上面的地址。")
	} else {
		fmt.Printf(" 本机访问：%s  ← 复制到浏览器打开\n", localURL)
		if cfg.Host == "0.0.0.0" || cfg.Host == "::" {
			for _, address := range lanAddresses() {
				fmt.Printf(" 局域网访问：http://%s:%d/\n", address, cfg.Port)
			}
		} else if cfg.Host != "127.0.0.1" && cfg.Host != "localhost" {
			fmt.Printf(" 监听地址：%s\n", cfg.Host)
		}
		if cfg.AuthEnabled {
			fmt.Println(" 登录认证：已启用")
		} else {
			fmt.Println(" 登录认证：未启用（单用户本地模式）")
		}
		fmt.Println(" 按 Ctrl+C 停止服务")
	}
	fmt.Println(strings.Repeat("=", 62))
}

func portInUse(host string, port int) bool {
	probe := host
	if host == "" || host == "0.0.0.0" {
		probe = "127.0.0.1"
	} else if host == "::" {
		probe = "::1"
	}
	conn, err := net.DialTimeout("tcp", net.JoinHostPort(probe, strconv.Itoa(port)), 700*time.Millisecond)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

func existingCellTracker(port int) bool {
	client := &http.Client{Timeout: 1500 * time.Millisecond}
	response, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/api/healthz", port))
	if err != nil {
		return false
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return false
	}
	var payload map[string]any
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		return false
	}
	return payload["ok"] == true
}

func waitForHealth(port int, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if existingCellTracker(port) {
			return true
		}
		time.Sleep(200 * time.Millisecond)
	}
	return false
}

func openBrowser(cfg *app.Config, url string) {
	var err error
	switch runtime.GOOS {
	case "windows":
		err = openWindowsBrowser(cfg, url)
	case "darwin":
		err = exec.Command("open", url).Start()
	default:
		err = exec.Command("xdg-open", url).Start()
	}
	if err != nil {
		log.Printf("自动打开浏览器失败：%v，请手动访问 %s", err, url)
		copyToClipboard(url)
		notifyUser("CellTracker", "未能自动打开浏览器。\n请手动访问：\n"+url+"\n\n地址已复制到剪贴板。")
		return
	}
	log.Printf("已尝试打开浏览器：%s", url)
}

func copyToClipboard(text string) {
	var command *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		command = exec.Command("clip")
	case "darwin":
		command = exec.Command("pbcopy")
	default:
		return
	}
	command.Stdin = strings.NewReader(text)
	_ = command.Run()
}

func openWindowsBrowser(cfg *app.Config, url string) error {
	candidates := []string{
		filepath.Join(os.Getenv("ProgramFiles"), "Google", "Chrome", "Application", "chrome.exe"),
		filepath.Join(os.Getenv("ProgramFiles(x86)"), "Google", "Chrome", "Application", "chrome.exe"),
		filepath.Join(os.Getenv("LOCALAPPDATA"), "Google", "Chrome", "Application", "chrome.exe"),
		filepath.Join(os.Getenv("ProgramFiles(x86)"), "Microsoft", "Edge", "Application", "msedge.exe"),
		filepath.Join(os.Getenv("ProgramFiles"), "Microsoft", "Edge", "Application", "msedge.exe"),
	}
	profile := filepath.Join(cfg.BaseDir, "browser-profile")
	for _, candidate := range candidates {
		if candidate == "" || !fileExists(candidate) {
			continue
		}
		profileDir := filepath.Join(profile, filepath.Base(candidate))
		existed := dirExists(profileDir)
		args := []string{
			"--user-data-dir=" + profileDir,
			"--no-first-run",
			"--no-default-browser-check",
			"--new-window",
			url,
		}
		if err := exec.Command(candidate, args...).Start(); err != nil {
			continue
		}
		// Chrome/Edge create the profile directory as soon as they really start.
		// If the process was rejected (for example by an elevated Edge instance),
		// the directory never appears, so fall through to the next method.
		if existed || waitForDir(profileDir, 3*time.Second) {
			return nil
		}
	}
	if err := exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start(); err == nil {
		return nil
	}
	return fmt.Errorf("未找到可用的浏览器")
}

func waitForDir(path string, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if dirExists(path) {
			return true
		}
		time.Sleep(100 * time.Millisecond)
	}
	return dirExists(path)
}

func dirExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func lanAddresses() []string {
	interfaces, err := net.Interfaces()
	if err != nil {
		return nil
	}
	seen := map[string]bool{}
	result := []string{}
	for _, iface := range interfaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, addr := range addrs {
			var ip net.IP
			switch value := addr.(type) {
			case *net.IPNet:
				ip = value.IP
			case *net.IPAddr:
				ip = value.IP
			}
			if ip == nil || ip.IsLoopback() || ip.IsLinkLocalUnicast() || ip.To4() == nil {
				continue
			}
			text := ip.String()
			if !seen[text] {
				seen[text] = true
				result = append(result, text)
			}
		}
	}
	return result
}

func pause() {
	if runtime.GOOS != "windows" {
		return
	}
	fmt.Print("按回车键退出…")
	_, _ = bufio.NewReader(os.Stdin).ReadString('\n')
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

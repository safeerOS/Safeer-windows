package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

//go:embed safeer-os-windows.zip
var embeddedZip []byte

const (
	MB_OK              = 0x00000000
	MB_ICONERROR       = 0x00000010
	MB_ICONINFORMATION = 0x00000040
	MB_YESNO           = 0x00000004
	IDYES              = 6
)

func showMessage(title, text string, style uint) int {
	user32 := syscall.NewLazyDLL("user32.dll")
	proc := user32.NewProc("MessageBoxW")
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	r, _, _ := proc.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), uintptr(style))
	return int(r)
}

func getAppDir() string {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		base = filepath.Join(os.Getenv("USERPROFILE"), "AppData", "Local")
	}
	if base == "" {
		base = os.TempDir()
	}
	return filepath.Join(base, "SafeerOS", "app")
}

func extractIfNeeded(targetDir string) error {
	h := sha256.Sum256(embeddedZip)
	currentHash := hex.EncodeToString(h[:])

	verFile := filepath.Join(targetDir, ".version")
	if data, err := os.ReadFile(verFile); err == nil {
		if strings.TrimSpace(string(data)) == currentHash {
			return nil
		}
	}

	if err := os.MkdirAll(targetDir, 0755); err != nil {
		return err
	}

	zr, err := zip.NewReader(bytes.NewReader(embeddedZip), int64(len(embeddedZip)))
	if err != nil {
		return fmt.Errorf("napaka pri branju paketa: %v", err)
	}

	for _, f := range zr.File {
		outPath := filepath.Join(targetDir, f.Name)
		if !strings.HasPrefix(filepath.Clean(outPath), filepath.Clean(targetDir)) {
			continue
		}

		if f.FileInfo().IsDir() {
			os.MkdirAll(outPath, 0755)
			continue
		}

		os.MkdirAll(filepath.Dir(outPath), 0755)
		rc, err := f.Open()
		if err != nil {
			return err
		}

		outFile, err := os.OpenFile(outPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, f.Mode())
		if err != nil {
			rc.Close()
			return err
		}

		_, err = io.Copy(outFile, rc)
		outFile.Close()
		rc.Close()
		if err != nil {
			return err
		}
	}

	os.WriteFile(verFile, []byte(currentHash), 0644)
	return nil
}

type PythonInfo struct {
	ExePath    string
	IsLauncher bool
}

func findPython() *PythonInfo {
	if p, err := exec.LookPath("py.exe"); err == nil {
		return &PythonInfo{ExePath: p, IsLauncher: true}
	}
	if p, err := exec.LookPath("py"); err == nil {
		return &PythonInfo{ExePath: p, IsLauncher: true}
	}
	for _, sysPy := range []string{
		`C:\WINDOWS\py.exe`,
		`C:\WINDOWS\system32\py.exe`,
	} {
		if _, err := os.Stat(sysPy); err == nil {
			return &PythonInfo{ExePath: sysPy, IsLauncher: true}
		}
	}

	if p, err := exec.LookPath("pythonw.exe"); err == nil {
		return &PythonInfo{ExePath: p}
	}
	if p, err := exec.LookPath("python.exe"); err == nil {
		return &PythonInfo{ExePath: p}
	}

	localAppData := os.Getenv("LOCALAPPDATA")
	userProfile := os.Getenv("USERPROFILE")
	patterns := []string{
		filepath.Join(localAppData, "Python", "pythoncore-*", "pythonw.exe"),
		filepath.Join(localAppData, "Python", "pythoncore-*", "python.exe"),
		filepath.Join(localAppData, "Programs", "Python", "Python*", "pythonw.exe"),
		filepath.Join(localAppData, "Programs", "Python", "Python*", "python.exe"),
		filepath.Join(userProfile, "AppData", "Local", "Programs", "Python", "Python*", "pythonw.exe"),
		filepath.Join(userProfile, "AppData", "Local", "Programs", "Python", "Python*", "python.exe"),
		`C:\Python*\pythonw.exe`,
		`C:\Python*\python.exe`,
		`C:\Program Files\Python*\pythonw.exe`,
		`C:\Program Files\Python*\python.exe`,
	}
	for _, pattern := range patterns {
		matches, _ := filepath.Glob(pattern)
		if len(matches) > 0 {
			return &PythonInfo{ExePath: matches[len(matches)-1]}
		}
	}

	return nil
}

func checkAndInstallPySide6(py *PythonInfo) error {
	var cmd *exec.Cmd
	checkScript := "import PySide6, qrcode"
	if py.IsLauncher {
		cmd = exec.Command(py.ExePath, "-3", "-c", checkScript)
	} else {
		cmd = exec.Command(py.ExePath, "-c", checkScript)
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	if err := cmd.Run(); err == nil {
		return nil
	}

	showMessage("Safeer OS", "Safeer OS pripravlja knjižnici PySide6 in python-vlc. Namestitev poteka v ozadju...", MB_ICONINFORMATION)
	var installCmd *exec.Cmd
	if py.IsLauncher {
		installCmd = exec.Command(py.ExePath, "-3", "-m", "pip", "install", "PySide6", "qrcode", "python-vlc")
	} else {
		installCmd = exec.Command(py.ExePath, "-m", "pip", "install", "PySide6", "qrcode", "python-vlc")
	}
	installCmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	if err := installCmd.Run(); err != nil {
		return fmt.Errorf("namestitev Python knjižnic ni uspela: %v", err)
	}
	return nil
}

func createDesktopShortcut(selfExe string) {
	desktop := filepath.Join(os.Getenv("USERPROFILE"), "Desktop")
	if _, err := os.Stat(desktop); err != nil {
		return
	}
	shortcutPath := filepath.Join(desktop, "Safeer OS.lnk")
	if _, err := os.Stat(shortcutPath); err == nil {
		return
	}

	psScript := fmt.Sprintf(
		`$s = (New-Object -COM WScript.Shell).CreateShortcut('%s'); $s.TargetPath = '%s'; $s.WorkingDirectory = '%s'; $s.Save()`,
		strings.ReplaceAll(shortcutPath, "'", "''"),
		strings.ReplaceAll(selfExe, "'", "''"),
		strings.ReplaceAll(filepath.Dir(selfExe), "'", "''"),
	)
	cmd := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", psScript)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	_ = cmd.Run()
}

func main() {
	targetDir := getAppDir()
	if err := extractIfNeeded(targetDir); err != nil {
		showMessage("Safeer OS - Napaka", fmt.Sprintf("Napaka pri pripravi datotek:\n%v", err), MB_ICONERROR)
		return
	}

	py := findPython()
	if py == nil {
		res := showMessage(
			"Safeer OS - Python ni najden",
			"Za zagon Safeer OS je potreben Python 3.\n\nAli želite odpreti uradno stran za prenos programa Python?",
			MB_ICONERROR|MB_YESNO,
		)
		if res == IDYES {
			cmd := exec.Command("rundll32", "url.dll,FileProtocolHandler", "https://www.python.org/downloads/")
			_ = cmd.Start()
		}
		return
	}

	if err := checkAndInstallPySide6(py); err != nil {
		showMessage("Safeer OS - Opozorilo", fmt.Sprintf("Opozorilo pri preverjanju PySide6:\n%v\n\nPoskušam zagnati aplikacijo...", err), MB_ICONINFORMATION)
	}

	selfExe, err := os.Executable()
	if err == nil {
		createDesktopShortcut(selfExe)
	}

	baseName := strings.ToLower(filepath.Base(os.Args[0]))
	targetScript := "windows/safeer_os_windows.py"
	if strings.Contains(baseName, "browser") {
		targetScript = "windows/launcher.py"
	}

	for _, a := range os.Args[1:] {
		if a == "--browser" || a == "-b" {
			targetScript = "windows/launcher.py"
		}
	}

	scriptFullPath := filepath.Join(targetDir, filepath.FromSlash(targetScript))

	var args []string
	if py.IsLauncher {
		args = append(args, "-3")
	}
	args = append(args, scriptFullPath)

	hasMode := false
	isControl := strings.Contains(baseName, "control")
	for _, a := range os.Args[1:] {
		if a == "--browser" || a == "-b" {
			continue
		}
		if a == "--control" || a == "-c" {
			isControl = true
			continue
		}
		if a == "--okno" || a == "--celozaslonsko" {
			hasMode = true
		}
		args = append(args, a)
	}

	if targetScript == "windows/safeer_os_windows.py" {
		if isControl {
			args = append(args, "--control", "--okno")
		} else if !hasMode {
			args = append(args, "--okno")
		}
	}

	cmd := exec.Command(py.ExePath, args...)
	cmd.Dir = targetDir
	cmd.Env = append(os.Environ(),
		"PYTHONPATH="+filepath.Join(targetDir, "windows")+";"+targetDir,
	)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}

	logFilePath := filepath.Join(targetDir, "safeer_os.log")
	logFile, logErr := os.OpenFile(logFilePath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0644)
	if logErr == nil {
		cmd.Stdout = logFile
		cmd.Stderr = logFile
	}

	if err := cmd.Start(); err != nil {
		showMessage("Safeer OS - Napaka", fmt.Sprintf("Zagon aplikacije ni uspel:\n%v", err), MB_ICONERROR)
		return
	}

	done := make(chan error, 1)
	go func() {
		done <- cmd.Wait()
	}()

	select {
	case err := <-done:
		if err != nil {
			if logFile != nil {
				logFile.Close()
			}
			vsebina, _ := os.ReadFile(logFilePath)
			msg := string(vsebina)
			if strings.TrimSpace(msg) == "" {
				msg = err.Error()
			}
			showMessage("Safeer OS - Napaka pri zagonu", fmt.Sprintf("Aplikacija se je nepričakovano zaključila:\n\n%s", msg), MB_ICONERROR)
		}
	case <-time.After(1200 * time.Millisecond):
		// Aplikacija se je uspešno zagnala in teče
	}
}

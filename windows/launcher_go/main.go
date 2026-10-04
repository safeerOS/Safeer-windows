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

// Pripona datoteke, ki je bila ob posodobitvi v rabi: umaknjena s preimenovanjem, pobrisana ob naslednjem zagonu.
const staraPripona = ".staro-"

// odpriZaPisanje odpre ciljno datoteko. Ce je v rabi (tece prejsnja kopija Safeer OS: SafeerMediaWebView.exe,
// knjiznice predvajalnika), je Windows ne pusti prepisati, preimenovati pa jo: staro umaknemo in zapisemo novo.
func odpriZaPisanje(outPath string, mode os.FileMode) (*os.File, error) {
	outFile, err := os.OpenFile(outPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, mode)
	if err == nil {
		return outFile, nil
	}
	if _, statErr := os.Stat(outPath); statErr != nil {
		return nil, err
	}
	for poskus := 0; poskus < 5; poskus++ {
		umaknjena := fmt.Sprintf("%s%s%d", outPath, staraPripona, time.Now().UnixNano())
		if os.Rename(outPath, umaknjena) == nil {
			return os.OpenFile(outPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, mode)
		}
		time.Sleep(300 * time.Millisecond)
		if outFile, err = os.OpenFile(outPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, mode); err == nil {
			return outFile, nil
		}
	}
	return nil, err
}

// pocistiUmaknjene pobrise datoteke, umaknjene ob prejsnji posodobitvi (tiste, ki so se v rabi, ostanejo do naslednjic).
func pocistiUmaknjene(targetDir string) {
	seznam := filepath.Join(targetDir, ".umaknjene")
	data, err := os.ReadFile(seznam)
	if err != nil {
		return
	}
	ostale := []string{}
	for _, pot := range strings.Split(string(data), "\n") {
		pot = strings.TrimSpace(pot)
		if pot == "" || !strings.Contains(filepath.Base(pot), staraPripona) ||
			!strings.HasPrefix(filepath.Clean(pot), filepath.Clean(targetDir)) {
			continue
		}
		if err := os.Remove(pot); err != nil && !os.IsNotExist(err) {
			ostale = append(ostale, pot)
		}
	}
	if len(ostale) == 0 {
		os.Remove(seznam)
		return
	}
	os.WriteFile(seznam, []byte(strings.Join(ostale, "\n")+"\n"), 0644)
}

// zabeleziUmaknjene v seznam doda datoteke *.staro-*, ki jih je posodobitev pustila ob novih.
func zabeleziUmaknjene(targetDir string) {
	najdene := []string{}
	filepath.Walk(targetDir, func(pot string, info os.FileInfo, err error) error {
		if err == nil && !info.IsDir() && strings.Contains(info.Name(), staraPripona) {
			najdene = append(najdene, pot)
		}
		return nil
	})
	if len(najdene) > 0 {
		os.WriteFile(filepath.Join(targetDir, ".umaknjene"), []byte(strings.Join(najdene, "\n")+"\n"), 0644)
	}
}

func extractIfNeeded(targetDir string) error {
	h := sha256.Sum256(embeddedZip)
	currentHash := hex.EncodeToString(h[:])

	pocistiUmaknjene(targetDir)
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

		outFile, err := odpriZaPisanje(outPath, f.Mode())
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

	zabeleziUmaknjene(targetDir)
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
	checkScript := "import PySide6, qrcode, mutagen, av, zeroconf, importlib.util; assert importlib.util.find_spec('mpv'); assert importlib.util.find_spec('winrt.windows.media.playback')"
	if py.IsLauncher {
		cmd = exec.Command(py.ExePath, "-3", "-c", checkScript)
	} else {
		cmd = exec.Command(py.ExePath, "-c", checkScript)
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	if err := cmd.Run(); err == nil {
		return nil
	}

	showMessage("Safeer OS", "Safeer OS pripravlja potrebne knjižnice (PySide6, python-vlc, python-mpv, mutagen, PyAV, zeroconf, WinRT za medijske tipke). Namestitev poteka v ozadju...", MB_ICONINFORMATION)
	var installCmd *exec.Cmd
	if py.IsLauncher {
		installCmd = exec.Command(py.ExePath, "-3", "-m", "pip", "install", "PySide6", "qrcode", "python-vlc", "mutagen", "av", "truststore", "zeroconf", "python-mpv==1.0.8", "winrt-runtime==3.2.1", "winrt-Windows.Foundation==3.2.1", "winrt-Windows.Foundation.Collections==3.2.1", "winrt-Windows.Media==3.2.1", "winrt-Windows.Media.Playback==3.2.1", "winrt-Windows.Storage.Streams==3.2.1")
	} else {
		installCmd = exec.Command(py.ExePath, "-m", "pip", "install", "PySide6", "qrcode", "python-vlc", "mutagen", "av", "truststore", "zeroconf", "python-mpv==1.0.8", "winrt-runtime==3.2.1", "winrt-Windows.Foundation==3.2.1", "winrt-Windows.Foundation.Collections==3.2.1", "winrt-Windows.Media==3.2.1", "winrt-Windows.Media.Playback==3.2.1", "winrt-Windows.Storage.Streams==3.2.1")
	}
	installCmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	if err := installCmd.Run(); err != nil {
		return fmt.Errorf("namestitev Python knjižnic ni uspela: %v", err)
	}
	return nil
}

// installPython namesti uradni Python 3.12 (python.org) prek winget, ce uporabnik to potrdi.
// Brez winget ali ob zavrnitvi vrne nil in main ponudi rocni prenos.
func installPython() *PythonInfo {
	winget, err := exec.LookPath("winget.exe")
	if err != nil {
		return nil
	}
	res := showMessage(
		"Safeer OS - potreben je Python",
		"Safeer OS za delovanje potrebuje Python 3 (brezplačen, python.org).\n\nAli ga Safeer OS namesti zdaj? Namestitev prek Windows upravitelja paketov (winget) traja nekaj minut, samo za tega uporabnika.",
		MB_ICONINFORMATION|MB_YESNO,
	)
	if res != IDYES {
		return nil
	}
	cmd := exec.Command(winget, "install", "--exact", "--id", "Python.Python.3.12", "--scope", "user",
		"--silent", "--accept-package-agreements", "--accept-source-agreements")
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	_ = cmd.Run()
	return findPython()
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
		py = installPython()
	}
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
		// Pot zaganjalnika za samodejno posodobitev (Safeer OS prepise ta exe z novim in ga zazene).
		_ = os.WriteFile(filepath.Join(targetDir, ".zaganjalnik"), []byte(selfExe), 0644)
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

	isControl := strings.Contains(baseName, "control")
	for _, a := range os.Args[1:] {
		if a == "--browser" || a == "-b" {
			continue
		}
		if a == "--control" || a == "-c" {
			isControl = true
			continue
		}
		args = append(args, a)
	}

	if targetScript == "windows/safeer_os_windows.py" {
		if isControl {
			args = append(args, "--control", "--okno")
		}
	}

	cmd := exec.Command(py.ExePath, args...)
	cmd.Dir = targetDir
	cmd.Env = append(os.Environ(),
		"PYTHONPATH="+filepath.Join(targetDir, "windows")+";"+targetDir,
		"PYTHONUNBUFFERED=1",
		"QTWEBENGINE_CHROMIUM_FLAGS=--autoplay-policy=no-user-gesture-required",
	)
	if selfExe != "" {
		// Safeer OS z njim registrira protokol magnet: (samo na uporabnikovo zahtevo): "<SafeerOS.exe>" --magnet "%1".
		cmd.Env = append(cmd.Env, "SAFEER_OS_EXE="+selfExe)
	}
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

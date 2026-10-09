package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

//go:embed safeer-os-windows.zip
var embeddedZip []byte

// paketOdtis je SHA-256 vdelanega paketa. Gradnja izdaje ga vpise (-ldflags "-X main.paketOdtis=<64 sestnajstiskih
// znakov>"), da ga zaganjalniku ni treba racunati ob vsakem zagonu: zgoscanje 80 MB traja okoli 0,2 s (izmerjeno na
// i5-4590), na hladnem disku pa se branje celega paketa. Pri razvojni gradnji je prazen in se izracuna.
var paketOdtis string

const (
	MB_OK              = 0x00000000
	MB_ICONERROR       = 0x00000010
	MB_ICONINFORMATION = 0x00000040
	MB_YESNO           = 0x00000004
	IDYES              = 6
)

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

// Pripona zacasne kopije zaganjalnika med prepisovanjem na stalno mesto (za njo je stevilka procesa).
const novaPripona = ".novo-"

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

// Seznam datotek, ki jih je namestil zadnji paket: ob naslednji namestitvi pobrisemo tiste, ki jih v novem ni vec.
const imeSeznama = ".datoteke"

// stevilke razcleni razlicico ("1.0.35") v stevila; del, ki ni stevilo, steje 0 ("1.0.35-test" -> 1, 0, 35).
func stevilke(razlicica string) []int {
	izid := []int{}
	for _, del := range strings.Split(strings.TrimSpace(razlicica), ".") {
		n := 0
		for _, znak := range del {
			if znak < '0' || znak > '9' {
				break
			}
			n = n*10 + int(znak-'0')
		}
		izid = append(izid, n)
	}
	return izid
}

// novejsa pove, ali je razlicica a strogo novejsa od b.
func novejsa(a, b string) bool {
	sa, sb := stevilke(a), stevilke(b)
	for i := 0; i < len(sa) || i < len(sb); i++ {
		x, y := 0, 0
		if i < len(sa) {
			x = sa[i]
		}
		if i < len(sb) {
			y = sb[i]
		}
		if x != y {
			return x > y
		}
	}
	return false
}

// razlicicaPaketa vrne razlicico v paketu (vnos windows/VERSION); "" ce je ni.
func razlicicaPaketa(zr *zip.Reader) string {
	for _, f := range zr.File {
		if f.Name != "windows/VERSION" {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			return ""
		}
		defer rc.Close()
		b, _ := io.ReadAll(io.LimitReader(rc, 64))
		return strings.TrimSpace(string(b))
	}
	return ""
}

// razlicicaNamescena vrne razlicico namescenega programa (app\windows\VERSION); "" ce je ni.
func razlicicaNamescena(targetDir string) string {
	b, err := os.ReadFile(filepath.Join(targetDir, "windows", "VERSION"))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

// namestitevCela pove, ali je v mapi uporabna namestitev (dokoncana razpakirava in glavni program).
func namestitevCela(targetDir string) bool {
	for _, ime := range []string{".version", filepath.Join("windows", "safeer_os_windows.py")} {
		if _, err := os.Stat(filepath.Join(targetDir, ime)); err != nil {
			return false
		}
	}
	return true
}

func vMapi(pot, mapa string) bool {
	return strings.HasPrefix(filepath.Clean(pot), filepath.Clean(mapa)+string(os.PathSeparator))
}

// odstraniOpuscene pobrise datoteke, ki jih je namestil prejsnji paket, v novem pa jih ni vec, in mape, ki so ostale
// prazne. Datotek, ki jih paket ni namestil (dnevnik, nastavitve), se ne dotakne.
func odstraniOpuscene(targetDir string, nove map[string]bool) int {
	data, err := os.ReadFile(filepath.Join(targetDir, imeSeznama))
	if err != nil {
		return 0
	}
	pobrisanih := 0
	for _, rel := range strings.Split(string(data), "\n") {
		rel = strings.TrimSpace(rel)
		if rel == "" || nove[rel] {
			continue
		}
		pot := filepath.Join(targetDir, filepath.FromSlash(rel))
		if !vMapi(pot, targetDir) {
			continue
		}
		if os.Remove(pot) != nil {
			continue
		}
		pobrisanih++
		for mapa := filepath.Dir(pot); vMapi(mapa, targetDir); mapa = filepath.Dir(mapa) {
			if os.Remove(mapa) != nil {
				break
			}
		}
	}
	return pobrisanih
}

func zapisiSeznam(targetDir string, nove map[string]bool) {
	imena := make([]string, 0, len(nove))
	for ime := range nove {
		imena = append(imena, ime)
	}
	sort.Strings(imena)
	os.WriteFile(filepath.Join(targetDir, imeSeznama), []byte(strings.Join(imena, "\n")+"\n"), 0644)
}

// razpakiraj namesti paket v targetDir, ce tam se ni prav ta. Vrne, ali je kaj namestil.
//
// Starejsi zaganjalnik novejse namestitve ne prepise: kdor odpre star preneseni exe, dobi program, ki je namescen
// (prej je star exe brez opozorila vrnil staro kodo in pustil mesanico obeh razlicic). `vsili` (--namesti) to
// preskoci - za namerno vrnitev na starejso razlicico.
func razpakiraj(paket []byte, targetDir string, vsili bool) (bool, error) {
	return razpakirajZOdtisom(paket, "", targetDir, vsili)
}

// jeOdtis: 64 malih sestnajstiskih znakov.
func jeOdtis(s string) bool {
	if len(s) != 64 {
		return false
	}
	for _, z := range s {
		if !(z >= '0' && z <= '9' || z >= 'a' && z <= 'f') {
			return false
		}
	}
	return true
}

// razpakirajZOdtisom: kot razpakiraj, le da odtis paketa (SHA-256) dobi od gradnje; prazen ali nepravilen izracuna.
func razpakirajZOdtisom(paket []byte, odtis, targetDir string, vsili bool) (bool, error) {
	currentHash := odtis
	if !jeOdtis(currentHash) {
		h := sha256.Sum256(paket)
		currentHash = hex.EncodeToString(h[:])
	}

	pocistiUmaknjene(targetDir)
	verFile := filepath.Join(targetDir, ".version")
	if data, err := os.ReadFile(verFile); err == nil {
		if strings.TrimSpace(string(data)) == currentHash {
			return false, nil
		}
	}

	zr, err := zip.NewReader(bytes.NewReader(paket), int64(len(paket)))
	if err != nil {
		return false, fmt.Errorf("napaka pri branju paketa: %v", err)
	}
	if !vsili && namestitevCela(targetDir) {
		nasa, namescena := razlicicaPaketa(zr), razlicicaNamescena(targetDir)
		if nasa != "" && namescena != "" && novejsa(namescena, nasa) {
			return false, nil
		}
	}

	if err := os.MkdirAll(targetDir, 0755); err != nil {
		return false, err
	}

	nove := map[string]bool{}
	for _, f := range zr.File {
		outPath := filepath.Join(targetDir, f.Name)
		if !vMapi(outPath, targetDir) {
			continue
		}

		if f.FileInfo().IsDir() {
			os.MkdirAll(outPath, 0755)
			continue
		}

		os.MkdirAll(filepath.Dir(outPath), 0755)
		rc, err := f.Open()
		if err != nil {
			return false, err
		}

		outFile, err := odpriZaPisanje(outPath, f.Mode())
		if err != nil {
			rc.Close()
			return false, err
		}

		_, err = io.Copy(outFile, rc)
		outFile.Close()
		rc.Close()
		if err != nil {
			return false, err
		}
		nove[filepath.ToSlash(f.Name)] = true
	}

	odstraniOpuscene(targetDir, nove)
	zapisiSeznam(targetDir, nove)
	zabeleziUmaknjene(targetDir)
	os.WriteFile(verFile, []byte(currentHash), 0644)
	return true, nil
}

// pocistiPosodobitve pobrise prenesene namestitvene datoteke, ki so svoje opravile: posodobitev novi exe prepise cez
// starega in zazene tega, preneseni pa je prej ostal za vedno (84 MB na posodobitev). Datoteke, iz katere tecemo
// (ce starega exe ni bilo mogoce prepisati), se ne dotakne; nedokoncan prenos in skripto pobrise sele, ko sta stara.
func pocistiPosodobitve(mapa, selfExe string) int {
	vnosi, err := os.ReadDir(mapa)
	if err != nil {
		return 0
	}
	pobrisanih := 0
	for _, v := range vnosi {
		if v.IsDir() {
			continue
		}
		pot := filepath.Join(mapa, v.Name())
		ime := strings.ToLower(v.Name())
		if strings.EqualFold(filepath.Clean(pot), filepath.Clean(selfExe)) || !strings.HasPrefix(ime, "safeeros") && ime != "posodobi.cmd" {
			continue
		}
		info, err := v.Info()
		if err != nil {
			continue
		}
		star := time.Since(info.ModTime()) > time.Hour
		if strings.HasSuffix(ime, ".exe") || star && (strings.HasSuffix(ime, ".del") || ime == "posodobi.cmd") {
			if os.Remove(pot) == nil {
				pobrisanih++
			}
		}
	}
	return pobrisanih
}

// stalnaPot je stalno mesto zaganjalnika ob mapi programa: %LOCALAPPDATA%\SafeerOS\SafeerOS.exe.
func stalnaPot(targetDir string) string {
	return filepath.Join(filepath.Dir(targetDir), "SafeerOS.exe")
}

func istaPot(a, b string) bool {
	return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
}

// istaDatoteka: ista pot ali ista datoteka pod drugim zapisom (kratko ime 8.3, kot ga ima %TEMP% pri dolgem
// uporabniskem imenu; povezava; preslikan pogon).
func istaDatoteka(a, b string) bool {
	if istaPot(a, b) {
		return true
	}
	sa, errA := os.Stat(a)
	sb, errB := os.Stat(b)
	return errA == nil && errB == nil && os.SameFile(sa, sb)
}

func jeDatoteka(pot string) bool {
	info, err := os.Stat(pot)
	return err == nil && info.Mode().IsRegular()
}

// kopirajDatoteko zapise cilj z vsebino vira prek zacasne datoteke: cilj je ves cas cel (star ali nov). Cilj, ki
// tece, Windows pusti preimenovati, ne pa prepisati: umaknemo ga, pobrise ga pocistiOstankeZaganjalnika.
func kopirajDatoteko(vir, cilj string) error {
	in, err := os.Open(vir)
	if err != nil {
		return err
	}
	defer in.Close()
	info, err := in.Stat()
	if err != nil {
		return err
	}
	zacasna := fmt.Sprintf("%s%s%d", cilj, novaPripona, os.Getpid())
	out, err := os.OpenFile(zacasna, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0755)
	if err != nil {
		return err
	}
	n, err := io.Copy(out, in)
	if cerr := out.Close(); err == nil {
		err = cerr
	}
	if err == nil && n != info.Size() {
		err = fmt.Errorf("prepisanih %d od %d bajtov", n, info.Size())
	}
	if err == nil {
		if err = os.Rename(zacasna, cilj); err != nil {
			umaknjena := fmt.Sprintf("%s%s%d", cilj, staraPripona, time.Now().UnixNano())
			if os.Rename(cilj, umaknjena) == nil {
				if err = os.Rename(zacasna, cilj); err != nil {
					os.Rename(umaknjena, cilj)
				}
			}
		}
	}
	if err != nil {
		os.Remove(zacasna)
	}
	return err
}

// pocistiOstankeZaganjalnika pobrise umaknjene stare kopije zaganjalnika (tista, ki se tece, ostane do naslednjic) in
// zacasne kopije prekinjenega prepisovanja (sele, ko so stare: drug zagon morda prav zdaj prepisuje).
func pocistiOstankeZaganjalnika(stalna string) int {
	vnosi, err := os.ReadDir(filepath.Dir(stalna))
	if err != nil {
		return 0
	}
	osnova := strings.ToLower(filepath.Base(stalna))
	pobrisanih := 0
	for _, v := range vnosi {
		ime := strings.ToLower(v.Name())
		if v.IsDir() || !strings.HasPrefix(ime, osnova+staraPripona) && !strings.HasPrefix(ime, osnova+novaPripona) {
			continue
		}
		if strings.HasPrefix(ime, osnova+novaPripona) {
			info, err := v.Info()
			if err != nil || time.Since(info.ModTime()) <= time.Hour {
				continue
			}
		}
		if os.Remove(filepath.Join(filepath.Dir(stalna), v.Name())) == nil {
			pobrisanih++
		}
	}
	return pobrisanih
}

// izberiZaganjalnik poskrbi, da zaganjalnik zivi na stalnem mestu, in vrne pot, na katero naj kazejo bliznjici,
// samodejna posodobitev (.zaganjalnik) in protokol magnet, ter ali je stalno kopijo pravkar zapisal.
//
// Prej je vse kazalo na datoteko, ki jo je uporabnik odprl (v Prenosih, na namizju, na kljucku): ko jo je pobrisal ali
// premaknil, je ikona ostala mrtva, posodobitev pa je prepisovala datoteko v Prenosih. Stalno kopijo zapise, ce je se
// ni ali ce je ta zaganjalnik pravkar namestil svojo razlicico (potem je on najnovejsi); starejsi zaganjalnik novejse
// stalne kopije ne prepise. Zaganjalnik s posebnim imenom (SafeerControl.exe ...) se ne kopira: ime doloca, kaj zazene.
func izberiZaganjalnik(selfExe, stalna, baseName string, razpakirano bool) (string, bool) {
	if istaDatoteka(selfExe, stalna) {
		return stalna, false
	}
	posebna := strings.Contains(baseName, "control") || strings.Contains(baseName, "browser")
	if !posebna && (razpakirano || !jeDatoteka(stalna)) {
		if kopirajDatoteko(selfExe, stalna) == nil {
			return stalna, true
		}
	}
	if jeDatoteka(stalna) {
		return stalna, false
	}
	return selfExe, false
}

// pripraviZaganjalnik uredi stalno kopijo zaganjalnika, zapis .zaganjalnik (pot za samodejno posodobitev: Safeer OS
// prepise ta exe z novim in ga zazene) in po potrebi bliznjici ter pocisti mapo posodobitve. Vrne pot zaganjalnika,
// ki jo dobi program (SAFEER_OS_EXE: registracija protokola magnet).
//
// Bliznjici uredimo le, kadar je kaj novega (namestitev, zaganjalnik na drugem mestu, vnosa v meniju Start ni): vsak
// zagon PowerShella bi sicer podaljsal vsak zagon programa. Zive bliznjice preusmerimo samo na stalno kopijo, ki je
// bila pravkar namescena ali posodobljena. Sveza namestitev (ikona na namizju nastane) je tista brez zapisa
// .zaganjalnik - tudi prva, ki se je prekinila pred koncem (zavrnjena namestitev Pythona).
func pripraviZaganjalnik(selfExe, targetDir, baseName, bliznjicaStart string, razpakirano bool, uredi func(exe string, sveza, premakni bool)) string {
	stalna := stalnaPot(targetDir)
	pocistiOstankeZaganjalnika(stalna)
	zaganjalnik, kopirano := izberiZaganjalnik(selfExe, stalna, baseName, razpakirano)
	premakni := (razpakirano || kopirano) && istaPot(zaganjalnik, stalna)
	zapis := filepath.Join(targetDir, ".zaganjalnik")
	zapisan, _ := os.ReadFile(zapis)
	sveza := strings.TrimSpace(string(zapisan)) == ""
	_, startErr := os.Stat(bliznjicaStart)
	if razpakirano || kopirano || strings.TrimSpace(string(zapisan)) != zaganjalnik || startErr != nil {
		uredi(zaganjalnik, sveza, premakni)
	}
	_ = os.WriteFile(zapis, []byte(zaganjalnik), 0644)
	pocistiPosodobitve(filepath.Join(filepath.Dir(targetDir), "posodobitve"), selfExe)
	return zaganjalnik
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

// Knjiznice Pythona preveri program sam (windows/safeer_windows/knjiznice.py), kadar ga zaganjalnik zazene z okoljem
// okoljePreverbe=1: ce kaj manjka, se konca s kodo kodaManjkajoKnjiznice, sicer v dnevnik izpise oznakaKnjizniceOK.
// Prej jih je zaganjalnik pred vsakim zagonom preveril s posebnim zagonom Pythona: okoli pol sekunde cakanja ob
// vsakem odpiranju programa.
const (
	okoljePreverbe        = "SAFEER_OS_PREVERI_KNJIZNICE"
	kodaManjkajoKnjiznice = 86
	oznakaKnjizniceOK     = "[SafeerOS] knjiznice OK"
)

// paketiPip so knjiznice, ki jih Safeer OS potrebuje (katere module preveri program, pove knjiznice.py).
//
// cryptography in Pillow: do 1.0.38 ju zaganjalnik ni namestil. Brez cryptography Safeer Link na cistem racunalniku
// ne more narediti svoje identitete (kljuc in potrdilo; rezerva je program openssl, ki ga Windows nima), brez Pillow
// racunalnik ne zajame zaslona za oddaljeni zaslon. Na razvojnem racunalniku sta bila namescena rocno.
var paketiPip = []string{
	"PySide6", "qrcode", "python-vlc", "mutagen", "av", "truststore", "zeroconf", "python-mpv==1.0.8",
	"cryptography", "Pillow", "dxcam",
	"winrt-runtime==3.2.1", "winrt-Windows.Foundation==3.2.1", "winrt-Windows.Foundation.Collections==3.2.1",
	"winrt-Windows.Media==3.2.1", "winrt-Windows.Media.Playback==3.2.1", "winrt-Windows.Storage.Streams==3.2.1",
}

func namestiKnjiznice(py *PythonInfo) error {
	// Samo obvestilo: MessageBoxW caka na klik, namestitev pa ne sme (do 1.0.46 je cakala, dokler uporabnik ni
	// potrdil okna - ob posodobitvi z novo knjiznico bi vsak uporabnik moral najprej klikniti).
	go showMessage("Safeer OS", "Safeer OS pripravlja potrebne knjižnice (PySide6, python-vlc, python-mpv, mutagen, PyAV, zeroconf, cryptography, Pillow, dxcam, WinRT za medijske tipke). Namestitev poteka v ozadju...", MB_ICONINFORMATION)
	args := []string{"-m", "pip", "install"}
	if py.IsLauncher {
		args = append([]string{"-3"}, args...)
	}
	installCmd := exec.Command(py.ExePath, append(args, paketiPip...)...)
	brezOkna(installCmd)
	if err := installCmd.Run(); err != nil {
		return fmt.Errorf("namestitev Python knjižnic ni uspela: %v", err)
	}
	return nil
}

const (
	zagonTece     = iota // program tece (ali se je koncal brez napake: drugi zagon je okno prepustil prvemu)
	zagonManjkajo        // program je javil, da mu manjkajo knjiznice
	zagonNapaka          // program se je koncal z napako
)

// kodaIzhoda vrne izhodno kodo koncanega programa: 0 brez napake, -1, ce napaka ni izhodna koda.
func kodaIzhoda(err error) int {
	if err == nil {
		return 0
	}
	var izhod *exec.ExitError
	if errors.As(err, &izhod) {
		return izhod.ExitCode()
	}
	return -1
}

// najvecDnevnik: nad to velikostjo se dnevnik pred zagonom prestavi v <ime>.1.
var najvecDnevnik int64 = 4 << 20

// odpriDnevnik odpre dnevnik programa za dopisovanje in vanj zapise vrstico o zagonu.
//
// Prej ga je vsak zagon skrajsal na nic: drug klik na ikono je prepisal dnevnik kopije, ki ze tece (ta je pisala naprej
// na starem odmiku - datoteka z luknjo iz nicel), in sled do napake je izginila.
func odpriDnevnik(pot string) (*os.File, error) {
	if info, err := os.Stat(pot); err == nil && info.Size() > najvecDnevnik {
		// Ce ga drzi kopija, ki tece, preimenovanje na Windows ne uspe: ostane in se prestavi ob kaksnem naslednjem zagonu.
		os.Remove(pot + ".1")
		os.Rename(pot, pot+".1")
	}
	f, err := os.OpenFile(pot, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err == nil {
		fmt.Fprintf(f, "===== zagon %s =====\n", time.Now().Format("2006-01-02 15:04:05"))
	}
	return f, err
}

// velikostDnevnika: kje v dnevniku se bo zacel izpis naslednjega zagona.
func velikostDnevnika(pot string) int64 {
	if info, err := os.Stat(pot); err == nil {
		return info.Size()
	}
	return 0
}

// preberiDnevnikOd vrne najvec `najvec` bajtov dnevnika od odmika `od` (izpis tega zagona). Ce je datoteka medtem
// krajsa od odmika (prestavljena ali skrajsana), bere od zacetka.
func preberiDnevnikOd(pot string, od, najvec int64) []byte {
	f, err := os.Open(pot)
	if err != nil {
		return nil
	}
	defer f.Close()
	if info, err := f.Stat(); err != nil || info.Size() < od {
		od = 0
	}
	if _, err := f.Seek(od, io.SeekStart); err != nil {
		return nil
	}
	b, _ := io.ReadAll(io.LimitReader(f, najvec))
	return b
}

// dnevnikPotrjuje pove, ali je program v tem zagonu (od odmika `od`) ze izpisal, da so knjiznice na mestu.
func dnevnikPotrjuje(dnevnik string, od int64) bool {
	return bytes.Contains(preberiDnevnikOd(dnevnik, od, 64<<10), []byte(oznakaKnjizniceOK))
}

// pocakajNaZagon caka, da se program konca ali da zazivi: da potrdi knjiznice (ce `cakaOznako`) in prezivi prvih
// `najmanj`. Po `najdlje` neha cakati tudi brez potrditve (zelo pocasen zagon, program brez preverbe).
func pocakajNaZagon(konec <-chan error, dnevnik string, od int64, cakaOznako bool, najmanj, najdlje time.Duration) (int, error) {
	zacetek := time.Now()
	potrjeno := !cakaOznako
	tik := time.NewTicker(100 * time.Millisecond)
	defer tik.Stop()
	for {
		select {
		case err := <-konec:
			switch {
			case err == nil:
				return zagonTece, nil
			case cakaOznako && kodaIzhoda(err) == kodaManjkajoKnjiznice:
				return zagonManjkajo, err
			}
			return zagonNapaka, err
		case <-tik.C:
			if !potrjeno {
				potrjeno = dnevnikPotrjuje(dnevnik, od)
			}
			if od := time.Since(zacetek); potrjeno && od >= najmanj || od >= najdlje {
				return zagonTece, nil
			}
		}
	}
}

// zazeniProgram zazene program in pocaka, da zazivi. Knjiznice preveri program sam; ce javi, da manjkajo, jih
// zaganjalnik namesti in program zazene znova - brez preverbe, kot doslej (tudi ce namestitev ni uspela: del programa
// dela tudi brez katere od njih). Vrne, ali program tece.
func zazeniProgram(zazeni func(preverba bool) (<-chan error, error), namesti func() error, sporoci func(naslov, besedilo string, slog uint),
	dnevnik string, najmanj, najdlje time.Duration) bool {
	od := velikostDnevnika(dnevnik) // dnevnik se dopisuje: izpis tega zagona se zacne tu
	konec, err := zazeni(true)
	if err != nil {
		sporoci("Safeer OS - Napaka", fmt.Sprintf("Zagon aplikacije ni uspel:\n%v", err), MB_ICONERROR)
		return false
	}
	stanje, izid := pocakajNaZagon(konec, dnevnik, od, true, najmanj, najdlje)
	if stanje == zagonManjkajo {
		if err := namesti(); err != nil {
			sporoci("Safeer OS - Opozorilo", fmt.Sprintf("Opozorilo pri nameščanju knjižnic:\n%v\n\nPoskušam zagnati aplikacijo...", err), MB_ICONINFORMATION)
		}
		od = velikostDnevnika(dnevnik)
		if konec, err = zazeni(false); err != nil {
			sporoci("Safeer OS - Napaka", fmt.Sprintf("Zagon aplikacije ni uspel:\n%v", err), MB_ICONERROR)
			return false
		}
		stanje, izid = pocakajNaZagon(konec, dnevnik, od, false, najmanj, najdlje)
	}
	if stanje == zagonTece {
		return true
	}
	msg := string(preberiDnevnikOd(dnevnik, od, 16<<10))
	if strings.TrimSpace(msg) == "" && izid != nil {
		msg = izid.Error()
	}
	sporoci("Safeer OS - Napaka pri zagonu", fmt.Sprintf("Aplikacija se je nepričakovano zaključila:\n\n%s", msg), MB_ICONERROR)
	return false
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
	brezOkna(cmd)
	_ = cmd.Run()
	return findPython()
}

func psNiz(s string) string {
	return "'" + strings.ReplaceAll(s, "'", "''") + "'"
}

// potBliznjiceStart je obicajno mesto vnosa v meniju Start (za hitro preverbo brez PowerShella).
func potBliznjiceStart() string {
	return filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "Safeer OS.lnk")
}

// skriptaBliznjic sestavi ukaze PowerShella, ki uredijo vnos v meniju Start in ikono na namizju:
//   - meni Start: vnos naredi, ce ga ni;
//   - namizje: ikono naredi samo ob prvi namestitvi (uporabnik jo sme pobrisati in se ne vrne);
//   - obstojeco bliznjico popravi, ce njen cilj ne obstaja vec (prej je za vedno kazala na izginuli exe, npr. na
//     kljucku USB), in jo preusmeri na `exe`, kadar je `premakni` (stalna kopija zaganjalnika je bila pravkar
//     namescena ali posodobljena: stara ikona je kazala na preneseno datoteko v Prenosih).
//
// Prazna `start` / `namizje` pomenita uporabnikovi mapi (tudi kadar je namizje preusmerjeno, npr. v OneDrive).
func skriptaBliznjic(exe, ikona, start, namizje string, sveza, premakni bool) string {
	potStart := "(Join-Path ([Environment]::GetFolderPath('Programs')) 'Safeer OS.lnk')"
	if start != "" {
		potStart = psNiz(start)
	}
	potNamizje := "(Join-Path ([Environment]::GetFolderPath('Desktop')) 'Safeer OS.lnk')"
	if namizje != "" {
		potNamizje = psNiz(namizje)
	}
	return strings.Join([]string{
		"$ErrorActionPreference = 'SilentlyContinue'",
		fmt.Sprintf("$exe = %s; $ikona = %s; $sveza = $%t; $premakni = $%t", psNiz(exe), psNiz(ikona), sveza, premakni),
		"$w = New-Object -ComObject WScript.Shell",
		"function Nastavi($pot) { $s = $w.CreateShortcut($pot); $s.TargetPath = $exe; $s.Arguments = ''; $s.WorkingDirectory = (Split-Path -Parent $exe); if (Test-Path -LiteralPath $ikona) { $s.IconLocation = $ikona + ',0' }; $s.Description = 'Safeer OS'; $s.Save() }",
		"function Cilj($pot) { if (Test-Path -LiteralPath $pot) { $w.CreateShortcut($pot).TargetPath } else { $null } }",
		"$start = " + potStart,
		"$namizje = " + potNamizje,
		"function Popravi($pot) { $c = Cilj $pot; if (-not $c -or -not (Test-Path -LiteralPath $c) -or ($premakni -and $c -ne $exe)) { Nastavi $pot } }",
		"if (Test-Path -LiteralPath $start) { Popravi $start } else { Nastavi $start }",
		"if (Test-Path -LiteralPath $namizje) { Popravi $namizje } elseif ($sveza) { Nastavi $namizje }",
	}, "\n")
}

// urediBliznjice pozene skripto v ozadju in ne caka nanjo: zagon programa se zaradi tega ne podaljsa.
func urediBliznjice(exe, targetDir string, sveza, premakni bool) {
	ikona := filepath.Join(targetDir, "windows", "safeer.ico")
	cmd := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", skriptaBliznjic(exe, ikona, "", "", sveza, premakni))
	brezOkna(cmd)
	_ = cmd.Start()
}

func main() {
	targetDir := getAppDir()
	vsili := false
	for _, a := range os.Args[1:] {
		if a == "--namesti" {
			vsili = true
		}
	}
	razpakirano, err := razpakirajZOdtisom(embeddedZip, paketOdtis, targetDir, vsili)
	if err != nil {
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

	baseName := strings.ToLower(filepath.Base(os.Args[0]))
	zaganjalnik := ""
	if selfExe, err := os.Executable(); err == nil {
		zaganjalnik = pripraviZaganjalnik(selfExe, targetDir, baseName, potBliznjiceStart(), razpakirano,
			func(exe string, sveza, premakni bool) { urediBliznjice(exe, targetDir, sveza, premakni) })
	}

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
		if a == "--namesti" {
			continue
		}
		args = append(args, a)
	}

	if targetScript == "windows/safeer_os_windows.py" {
		if isControl {
			args = append(args, "--control", "--okno")
		}
	}

	logFilePath := filepath.Join(targetDir, "safeer_os.log")
	zazeni := func(preverba bool) (<-chan error, error) {
		cmd := exec.Command(py.ExePath, args...)
		cmd.Dir = targetDir
		cmd.Env = append(os.Environ(),
			"PYTHONPATH="+filepath.Join(targetDir, "windows")+";"+targetDir,
			"PYTHONUNBUFFERED=1",
			"QTWEBENGINE_CHROMIUM_FLAGS=--autoplay-policy=no-user-gesture-required",
		)
		if zaganjalnik != "" {
			// Safeer OS z njim registrira protokol magnet: (samo na uporabnikovo zahtevo): "<SafeerOS.exe>" --magnet "%1".
			cmd.Env = append(cmd.Env, "SAFEER_OS_EXE="+zaganjalnik)
		}
		if preverba {
			cmd.Env = append(cmd.Env, okoljePreverbe+"=1")
		}
		brezOkna(cmd)
		logFile, logErr := odpriDnevnik(logFilePath)
		if logErr == nil {
			cmd.Stdout = logFile
			cmd.Stderr = logFile
		}
		err := cmd.Start()
		if logFile != nil {
			logFile.Close() // program ima svojo, podedovano
		}
		if err != nil {
			return nil, err
		}
		konec := make(chan error, 1)
		go func() { konec <- cmd.Wait() }()
		return konec, nil
	}
	// Program zazivi, ko potrdi knjiznice in prezivi prvih 1,2 s (napako ob zagonu pokazemo z dnevnikom).
	zazeniProgram(zazeni, func() error { return namestiKnjiznice(py) },
		func(naslov, besedilo string, slog uint) { showMessage(naslov, besedilo, slog) },
		logFilePath, 1200*time.Millisecond, 30*time.Second)
}

package main

import (
	"archive/zip"
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"
)

// Preizkusni program zna tudi samo »teci nekaj sekund«: tako dobimo izvrsljivo datoteko v rabi.
func TestMain(m *testing.M) {
	if os.Getenv("SAFEER_PREIZKUS_SPI") == "1" {
		time.Sleep(6 * time.Second)
		return
	}
	// ... in »koncaj se s to kodo«: prava napaka podprocesa z izhodno kodo.
	if koda := os.Getenv("SAFEER_PREIZKUS_KODA"); koda != "" {
		n, _ := strconv.Atoi(koda)
		os.Exit(n)
	}
	os.Exit(m.Run())
}

func umaknjene(t *testing.T, mapa string) []string {
	t.Helper()
	vnosi, err := os.ReadDir(mapa)
	if err != nil {
		t.Fatal(err)
	}
	najdene := []string{}
	for _, v := range vnosi {
		if strings.Contains(v.Name(), staraPripona) {
			najdene = append(najdene, v.Name())
		}
	}
	return najdene
}

func TestNavadnaDatotekaSePrepiseBrezUmikanja(t *testing.T) {
	mapa := t.TempDir()
	pot := filepath.Join(mapa, "os.js")
	if err := os.WriteFile(pot, []byte("staro"), 0644); err != nil {
		t.Fatal(err)
	}
	f, err := odpriZaPisanje(pot, 0644)
	if err != nil {
		t.Fatalf("odpriZaPisanje: %v", err)
	}
	f.WriteString("novo")
	f.Close()
	if vsebina, _ := os.ReadFile(pot); string(vsebina) != "novo" {
		t.Fatalf("vsebina: %q", vsebina)
	}
	if u := umaknjene(t, mapa); len(u) != 0 {
		t.Fatalf("umaknjene brez potrebe: %v", u)
	}
	// Nova datoteka (ni je se): navadno ustvarjanje.
	nova, err := odpriZaPisanje(filepath.Join(mapa, "novo.py"), 0644)
	if err != nil {
		t.Fatalf("nova datoteka: %v", err)
	}
	nova.Close()
}

func TestSeznamUmaknjenihSePocisti(t *testing.T) {
	mapa := t.TempDir()
	stara := filepath.Join(mapa, "knjiznica.dll"+staraPripona+"123")
	tuja := filepath.Join(t.TempDir(), "tuja.dll"+staraPripona+"1")
	for _, p := range []string{stara, tuja, filepath.Join(mapa, "ostane.txt")} {
		if err := os.WriteFile(p, []byte("x"), 0644); err != nil {
			t.Fatal(err)
		}
	}
	zabeleziUmaknjene(mapa)
	seznam := filepath.Join(mapa, ".umaknjene")
	data, err := os.ReadFile(seznam)
	if err != nil || strings.TrimSpace(string(data)) != stara {
		t.Fatalf("seznam: %q (%v)", data, err)
	}
	// Vrstica zunaj mape aplikacije in vrstica brez pripone se ne brise.
	os.WriteFile(seznam, []byte(stara+"\n"+tuja+"\n"+filepath.Join(mapa, "ostane.txt")+"\n"), 0644)
	pocistiUmaknjene(mapa)
	if _, err := os.Stat(stara); !os.IsNotExist(err) {
		t.Fatal("umaknjena datoteka ni pobrisana")
	}
	for _, p := range []string{tuja, filepath.Join(mapa, "ostane.txt")} {
		if _, err := os.Stat(p); err != nil {
			t.Fatalf("%s ne bi smela biti pobrisana", p)
		}
	}
	if _, err := os.Stat(seznam); !os.IsNotExist(err) {
		t.Fatal("prazen seznam bi moral izginiti")
	}
}

// Posodobitev ob odprtem Safeer OS: SafeerMediaWebView.exe tece, Windows ga ne pusti prepisati.
func TestIzvrsljivaDatotekaVRabiSeUmakneInZamenja(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("datoteka v rabi, ki je ni mogoce prepisati, je posebnost Windows")
	}
	mapa, err := os.MkdirTemp("", "safeer-zaganjalnik-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(mapa)
	exe := filepath.Join(mapa, "SafeerMediaWebView.exe")
	jaz, _ := os.Executable()
	podatki, err := os.ReadFile(jaz)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(exe, podatki, 0755); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(exe)
	cmd.Env = append(os.Environ(), "SAFEER_PREIZKUS_SPI=1")
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	koncan := false
	defer func() {
		if !koncan {
			cmd.Process.Kill()
			cmd.Wait()
		}
	}()
	time.Sleep(700 * time.Millisecond)

	if f, err := os.OpenFile(exe, os.O_WRONLY|os.O_TRUNC, 0755); err == nil {
		f.Close()
		t.Fatal("tekoco datoteko je bilo mogoce prepisati - preizkus ne preizkusa nicesar")
	}
	f, err := odpriZaPisanje(exe, 0755)
	if err != nil {
		t.Fatalf("odpriZaPisanje datoteke v rabi: %v", err)
	}
	f.WriteString("nova razlicica")
	f.Close()
	if vsebina, _ := os.ReadFile(exe); string(vsebina) != "nova razlicica" {
		t.Fatalf("nova vsebina ni zapisana (%d bajtov)", len(vsebina))
	}
	if u := umaknjene(t, mapa); len(u) != 1 {
		t.Fatalf("pricakovana ena umaknjena datoteka, najdene: %v", u)
	}

	// Dokler stara kopija tece, umaknjene datoteke ni mogoce pobrisati: ostane na seznamu.
	zabeleziUmaknjene(mapa)
	pocistiUmaknjene(mapa)
	if u := umaknjene(t, mapa); len(u) != 1 {
		t.Fatalf("datoteka v rabi je izginila: %v", u)
	}
	if _, err := os.Stat(filepath.Join(mapa, ".umaknjene")); err != nil {
		t.Fatal("seznam umaknjenih bi moral ostati")
	}

	cmd.Process.Kill()
	cmd.Wait()
	koncan = true
	time.Sleep(300 * time.Millisecond)
	pocistiUmaknjene(mapa)
	if u := umaknjene(t, mapa); len(u) != 0 {
		t.Fatalf("po koncu stare kopije umaknjena datoteka ni pobrisana: %v", u)
	}
	if _, err := os.Stat(filepath.Join(mapa, ".umaknjene")); !os.IsNotExist(err) {
		t.Fatal("seznam umaknjenih bi moral izginiti")
	}
}

// ---------------------------------------------------------------------------------------------------------------
// Razlicice, starejsi paket, opuscene datoteke, mapa posodobitve, bliznjici (krog 105).

func paket(t *testing.T, datoteke map[string]string) []byte {
	t.Helper()
	imena := make([]string, 0, len(datoteke))
	for ime := range datoteke {
		imena = append(imena, ime)
	}
	sort.Strings(imena)
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for _, ime := range imena {
		w, err := zw.Create(ime)
		if err != nil {
			t.Fatal(err)
		}
		w.Write([]byte(datoteke[ime]))
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func vsebina(pot string) string {
	b, err := os.ReadFile(pot)
	if err != nil {
		return "<ni>"
	}
	return string(b)
}

func obstaja(pot string) bool {
	_, err := os.Stat(pot)
	return err == nil
}

func namesti(t *testing.T, p []byte, mapa string, vsili, pricakovano bool, opis string) {
	t.Helper()
	ok, err := razpakiraj(p, mapa, vsili)
	if err != nil {
		t.Fatalf("%s: %v", opis, err)
	}
	if ok != pricakovano {
		t.Fatalf("%s: razpakirano=%v, pricakovano %v", opis, ok, pricakovano)
	}
}

func TestNovejsa(t *testing.T) {
	for _, p := range []struct {
		a, b        string
		pricakovano bool
	}{
		{"1.0.36", "1.0.35", true}, {"1.0.35", "1.0.36", false}, {"1.0.10", "1.0.9", true}, {"1.0.9", "1.0.10", false},
		{"1.0.35", "1.0.35", false}, {"1.1", "1.0.99", true}, {"1.0", "1.0.0", false}, {"2", "1.9.9", true},
		{"1.0.36-test", "1.0.35", true}, {"1.0.35-test", "1.0.35", false}, {"", "1.0.0", false}, {"smeti", "0.0.1", false},
		{" 1.0.36\n", "1.0.35", true},
	} {
		if novejsa(p.a, p.b) != p.pricakovano {
			t.Errorf("novejsa(%q, %q) = %v", p.a, p.b, !p.pricakovano)
		}
	}
}

// 4. 10. 2026: z namizja zagnan SafeerOS-Windows-1.0.17.exe je prepisal namesceno 1.0.35 (in pustil mesanico obeh).
func TestStarejsiPaketNePrepiseNovejseNamestitve(t *testing.T) {
	mapa := filepath.Join(t.TempDir(), "app")
	nov := paket(t, map[string]string{"windows/VERSION": "1.0.36\n", "windows/safeer_os_windows.py": "nov", "core/a.py": "nov", "core/samo_nova.py": "nov"})
	star := paket(t, map[string]string{"windows/VERSION": "1.0.17\n", "windows/safeer_os_windows.py": "star", "core/a.py": "star"})
	namesti(t, nov, mapa, false, true, "prva namestitev")
	zapis := vsebina(filepath.Join(mapa, ".version"))

	namesti(t, star, mapa, false, false, "starejsi paket cez novejso namestitev")
	if vsebina(filepath.Join(mapa, "core", "a.py")) != "nov" || razlicicaNamescena(mapa) != "1.0.36" {
		t.Fatal("starejsi paket je spremenil novejso namestitev")
	}
	if vsebina(filepath.Join(mapa, ".version")) != zapis {
		t.Fatal("zapis o namescenem paketu se je spremenil")
	}
	namesti(t, nov, mapa, false, false, "isti paket se enkrat")

	// Namerna vrnitev na starejso razlicico (--namesti): cela, brez ostankov novejse.
	namesti(t, star, mapa, true, true, "vsiljena starejsa razlicica")
	if vsebina(filepath.Join(mapa, "core", "a.py")) != "star" || razlicicaNamescena(mapa) != "1.0.17" {
		t.Fatal("vsiljena namestitev ni zamenjala datotek")
	}
	if obstaja(filepath.Join(mapa, "core", "samo_nova.py")) {
		t.Fatal("po vrnitvi na starejso razlicico je ostala datoteka novejse (mesanica)")
	}
	namesti(t, nov, mapa, false, true, "novejsi paket cez starejso namestitev")
	if vsebina(filepath.Join(mapa, "core", "a.py")) != "nov" {
		t.Fatal("novejsi paket ni zamenjal datotek")
	}
}

func TestIstaRazlicicaZDrugoVsebinoSeNamesti(t *testing.T) {
	mapa := filepath.Join(t.TempDir(), "app")
	namesti(t, paket(t, map[string]string{"windows/VERSION": "1.0.36", "windows/safeer_os_windows.py": "a"}), mapa, false, true, "prva")
	namesti(t, paket(t, map[string]string{"windows/VERSION": "1.0.36", "windows/safeer_os_windows.py": "b"}), mapa, false, true, "ista razlicica, druga gradnja")
	if vsebina(filepath.Join(mapa, "windows", "safeer_os_windows.py")) != "b" {
		t.Fatal("druga gradnja iste razlicice ni namescena")
	}
}

func TestNedokoncanaNamestitevSePrepise(t *testing.T) {
	mapa := filepath.Join(t.TempDir(), "app")
	os.MkdirAll(filepath.Join(mapa, "windows"), 0755)
	os.WriteFile(filepath.Join(mapa, "windows", "VERSION"), []byte("9.9.9"), 0644)
	os.WriteFile(filepath.Join(mapa, "windows", "safeer_os_windows.py"), []byte("pol"), 0644)
	// Zapisa .version ni: razpakirava se ni koncala. Tudi starejsi paket jo mora popraviti.
	star := paket(t, map[string]string{"windows/VERSION": "1.0.17", "windows/safeer_os_windows.py": "cel"})
	namesti(t, star, mapa, false, true, "nedokoncana namestitev")
	if vsebina(filepath.Join(mapa, "windows", "safeer_os_windows.py")) != "cel" {
		t.Fatal("nedokoncana namestitev ni popravljena")
	}
	// Paket brez razlicice (zelo star) in namestitev brez razlicice: kot doslej - namesti se.
	brez := paket(t, map[string]string{"windows/safeer_os_windows.py": "brez"})
	namesti(t, brez, mapa, false, true, "paket brez razlicice")
}

func TestOpusceneDatotekeIzginejo(t *testing.T) {
	koren := t.TempDir()
	mapa := filepath.Join(koren, "app")
	v1 := paket(t, map[string]string{"windows/VERSION": "1.0.36", "windows/safeer_os_windows.py": "1", "core/a.py": "1",
		"core/stara.py": "1", "core/staro/globlje/modul.py": "1", "assets/os/os.js": "1"})
	namesti(t, v1, mapa, false, true, "v1")
	// Datoteke, ki jih paket ni namestil.
	os.WriteFile(filepath.Join(mapa, "safeer_os.log"), []byte("dnevnik"), 0644)
	os.WriteFile(filepath.Join(mapa, "core", "uporabnikova.txt"), []byte("moje"), 0644)

	v2 := paket(t, map[string]string{"windows/VERSION": "1.0.37", "windows/safeer_os_windows.py": "2", "core/a.py": "2",
		"core/nova.py": "2", "assets/os/os.js": "2"})
	namesti(t, v2, mapa, false, true, "v2")
	for _, izginula := range []string{"core/stara.py", "core/staro/globlje/modul.py", "core/staro/globlje", "core/staro"} {
		if obstaja(filepath.Join(mapa, filepath.FromSlash(izginula))) {
			t.Errorf("%s bi morala izginiti", izginula)
		}
	}
	for pot, pricakovano := range map[string]string{"core/a.py": "2", "core/nova.py": "2", "assets/os/os.js": "2",
		"safeer_os.log": "dnevnik", "core/uporabnikova.txt": "moje"} {
		if v := vsebina(filepath.Join(mapa, filepath.FromSlash(pot))); v != pricakovano {
			t.Errorf("%s = %q, pricakovano %q", pot, v, pricakovano)
		}
	}
	seznam := strings.Fields(vsebina(filepath.Join(mapa, imeSeznama)))
	if strings.Join(seznam, " ") != "assets/os/os.js core/a.py core/nova.py windows/VERSION windows/safeer_os_windows.py" {
		t.Fatalf("seznam namescenih datotek: %v", seznam)
	}

	// Vrstica v seznamu, ki kaze iz mape programa, se ne brise.
	tuja := filepath.Join(koren, "tuja.txt")
	os.WriteFile(tuja, []byte("ni nasa"), 0644)
	f, _ := os.OpenFile(filepath.Join(mapa, imeSeznama), os.O_APPEND|os.O_WRONLY, 0644)
	f.WriteString("../tuja.txt\n" + tuja + "\n")
	f.Close()
	v3 := paket(t, map[string]string{"windows/VERSION": "1.0.38", "windows/safeer_os_windows.py": "3"})
	namesti(t, v3, mapa, false, true, "v3")
	if vsebina(tuja) != "ni nasa" {
		t.Fatal("pobrisana je datoteka zunaj mape programa")
	}
	if obstaja(filepath.Join(mapa, "core", "a.py")) || !obstaja(filepath.Join(mapa, "core", "uporabnikova.txt")) {
		t.Fatal("v3: opuscena datoteka je ostala ali pa je izginila uporabnikova")
	}
}

func TestPocistiPosodobitve(t *testing.T) {
	mapa := t.TempDir()
	jaz := filepath.Join(mapa, "SafeerOS-Windows-1.0.37.exe")
	pred2h := time.Now().Add(-2 * time.Hour)
	for ime, star := range map[string]bool{"SafeerOS-Windows-1.0.18.exe": true, "SafeerOS-Windows-1.0.19.exe": false,
		"SafeerOS-Windows-1.0.37.exe": true, "SafeerOS-Windows-1.0.38.exe.del": false, "SafeerOS-Windows-1.0.30.exe.del": true,
		"posodobi.cmd": false, "zapiski.txt": true, "drug-program.exe": true} {
		pot := filepath.Join(mapa, ime)
		if err := os.WriteFile(pot, []byte("x"), 0644); err != nil {
			t.Fatal(err)
		}
		if star {
			os.Chtimes(pot, pred2h, pred2h)
		}
	}
	os.MkdirAll(filepath.Join(mapa, "SafeerOS-mapa.exe"), 0755)

	if n := pocistiPosodobitve(mapa, jaz); n != 3 {
		t.Fatalf("pobrisanih %d, pricakovano 3", n)
	}
	ostale := []string{}
	vnosi, _ := os.ReadDir(mapa)
	for _, v := range vnosi {
		ostale = append(ostale, v.Name())
	}
	sort.Strings(ostale)
	pricakovano := "SafeerOS-Windows-1.0.37.exe SafeerOS-Windows-1.0.38.exe.del SafeerOS-mapa.exe drug-program.exe posodobi.cmd zapiski.txt"
	if strings.Join(ostale, " ") != pricakovano {
		t.Fatalf("ostalo: %v", ostale)
	}
	// Skripta posodobitve gre, ko je stara (med posodobitvijo se se izvaja).
	cmd := filepath.Join(mapa, "posodobi.cmd")
	os.Chtimes(cmd, pred2h, pred2h)
	if n := pocistiPosodobitve(mapa, strings.ToUpper(jaz)); n != 1 || obstaja(cmd) || !obstaja(jaz) {
		t.Fatalf("stara skripta: pobrisanih %d, skripta obstaja %v, zaganjalnik obstaja %v", n, obstaja(cmd), obstaja(jaz))
	}
	if n := pocistiPosodobitve(filepath.Join(mapa, "ni-je"), jaz); n != 0 {
		t.Fatalf("mapa, ki je ni: %d", n)
	}
}

func TestSkriptaBliznjic(t *testing.T) {
	exe := `C:\Users\O'Neil\AppData\Local\SafeerOS\SafeerOS.exe`
	s := skriptaBliznjic(exe, `C:\x\safeer.ico`, "", "", true, false)
	for _, potrebno := range []string{`$exe = 'C:\Users\O''Neil\AppData\Local\SafeerOS\SafeerOS.exe'`, `$ikona = 'C:\x\safeer.ico'`,
		"$sveza = $true; $premakni = $false", "GetFolderPath('Programs')", "GetFolderPath('Desktop')"} {
		if !strings.Contains(s, potrebno) {
			t.Errorf("v skripti manjka: %s", potrebno)
		}
	}
	s = skriptaBliznjic(exe, "", `D:\a\Start.lnk`, `D:\b\Namizje.lnk`, false, true)
	for _, potrebno := range []string{`$start = 'D:\a\Start.lnk'`, `$namizje = 'D:\b\Namizje.lnk'`, "$sveza = $false; $premakni = $true"} {
		if !strings.Contains(s, potrebno) {
			t.Errorf("v skripti manjka: %s", potrebno)
		}
	}
	if strings.Contains(s, "GetFolderPath") {
		t.Error("podani poti bi morali nadomestiti uporabnikovi mapi")
	}
}

// Prava bliznjica .lnk: nastanek, mrtva ikona (4. 10. 2026 je ikona na namizju kazala na izginuli D:\SafeerOS.exe),
// pobrisana ikona, ki se ne sme vrniti, in ziva ikona, ki kaze drugam.
func TestBliznjiciNaWindows(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("bliznjice .lnk so posebnost Windows")
	}
	mapa, err := os.MkdirTemp("", "safeer-bliznjice-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(mapa)
	exe, _ := os.Executable()
	// %TEMP% ima pri dolgem uporabniskem imenu kratko obliko (C:\Users\RUNNER~1\...), bliznjica pa vrne dolgo pot.
	if dolga, err := filepath.EvalSymlinks(mapa); err == nil {
		mapa = dolga
	}
	if dolga, err := filepath.EvalSymlinks(exe); err == nil {
		exe = dolga
	}
	start := filepath.Join(mapa, "Start", "Safeer OS.lnk")
	namizje := filepath.Join(mapa, "Namizje", "Safeer OS.lnk")
	ikona := filepath.Join(mapa, "ni.ico")
	os.MkdirAll(filepath.Dir(start), 0755)
	os.MkdirAll(filepath.Dir(namizje), 0755)
	pozeni := func(skripta string) string {
		izhod, err := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", skripta).CombinedOutput()
		if err != nil {
			t.Fatalf("powershell: %v\n%s", err, izhod)
		}
		return strings.TrimSpace(string(izhod))
	}
	cilj := func(pot string) string {
		return pozeni("(New-Object -ComObject WScript.Shell).CreateShortcut(" + psNiz(pot) + ").TargetPath")
	}
	isti := func(a, b string) bool { return strings.EqualFold(filepath.Clean(a), filepath.Clean(b)) }

	// 1. Prva namestitev: vnos v meniju Start in ikona na namizju.
	pozeni(skriptaBliznjic(exe, ikona, start, namizje, true, true))
	if !isti(cilj(start), exe) || !isti(cilj(namizje), exe) {
		t.Fatalf("prva namestitev: start=%q namizje=%q", cilj(start), cilj(namizje))
	}
	// 2. Uporabnik ikono na namizju pobrise: ob naslednjih zagonih in posodobitvah se ne vrne; vnos v meniju Start, ki ga ni, pa.
	os.Remove(namizje)
	os.Remove(start)
	pozeni(skriptaBliznjic(exe, ikona, start, namizje, false, true))
	if obstaja(namizje) {
		t.Fatal("pobrisana ikona na namizju se je vrnila")
	}
	if !isti(cilj(start), exe) {
		t.Fatal("manjkajoci vnos v meniju Start ni nastal")
	}
	// 3. Mrtva ikona in mrtev vnos (cilj ne obstaja vec) se popravita ob navadnem zagonu.
	mrtev := filepath.Join(mapa, "ni-ga", "SafeerOS.exe")
	pozeni(skriptaBliznjic(mrtev, ikona, start, namizje, true, true))
	if !isti(cilj(start), mrtev) || !isti(cilj(namizje), mrtev) {
		t.Fatalf("priprava mrtvih bliznjic: start=%q namizje=%q", cilj(start), cilj(namizje))
	}
	pozeni(skriptaBliznjic(exe, ikona, start, namizje, false, false))
	if !isti(cilj(start), exe) || !isti(cilj(namizje), exe) {
		t.Fatalf("mrtvi bliznjici nista popravljeni: start=%q namizje=%q", cilj(start), cilj(namizje))
	}
	// 4. Zivi bliznjici, ki kazeta drugam (preneseni exe v Prenosih): navaden zagon ju pusti; ko je stalna kopija
	// zaganjalnika namescena ali posodobljena, se obe preusmerita nanjo.
	stalna := filepath.Join(mapa, "SafeerOS.exe")
	os.WriteFile(stalna, []byte("x"), 0644)
	pozeni(skriptaBliznjic(stalna, ikona, start, namizje, false, false))
	if !isti(cilj(start), exe) || !isti(cilj(namizje), exe) {
		t.Fatalf("navaden zagon je preusmeril zivi bliznjici: start=%q namizje=%q", cilj(start), cilj(namizje))
	}
	pozeni(skriptaBliznjic(stalna, ikona, start, namizje, false, true))
	if !isti(cilj(start), stalna) || !isti(cilj(namizje), stalna) {
		t.Fatalf("bliznjici nista preusmerjeni na stalno kopijo: start=%q namizje=%q", cilj(start), cilj(namizje))
	}
	// 5. Tudi ob preusmeritvi se pobrisana ikona na namizju ne vrne.
	os.Remove(namizje)
	pozeni(skriptaBliznjic(exe, ikona, start, namizje, false, true))
	if obstaja(namizje) || !isti(cilj(start), exe) {
		t.Fatalf("po preusmeritvi: ikona na namizju obstaja %v, start=%q", obstaja(namizje), cilj(start))
	}
}

// ---------------------------------------------------------------------------------------------------------------
// Stalno mesto zaganjalnika (krog 105).

func zapisi(t *testing.T, pot, besedilo string) {
	t.Helper()
	os.MkdirAll(filepath.Dir(pot), 0755)
	if err := os.WriteFile(pot, []byte(besedilo), 0755); err != nil {
		t.Fatal(err)
	}
}

func imena(t *testing.T, mapa string) string {
	t.Helper()
	vnosi, err := os.ReadDir(mapa)
	if err != nil {
		t.Fatal(err)
	}
	vsa := []string{}
	for _, v := range vnosi {
		vsa = append(vsa, v.Name())
	}
	sort.Strings(vsa)
	return strings.Join(vsa, " ")
}

func TestVnosIzvenMapeProgramaSeNeRazpakira(t *testing.T) {
	koren := t.TempDir()
	mapa := filepath.Join(koren, "app")
	p := paket(t, map[string]string{"windows/VERSION": "1.0.36", "windows/safeer_os_windows.py": "ok",
		"../zunaj.txt": "x", "../app-sosed/x.txt": "x", "../../visje.txt": "x"})
	// Novejsi Go tak paket lahko zavrne ze pri branju; v obeh primerih zunaj mape programa ne sme nastati nic.
	razpakiraj(p, mapa, false)
	for _, pot := range []string{filepath.Join(koren, "zunaj.txt"), filepath.Join(koren, "app-sosed"), filepath.Join(filepath.Dir(koren), "visje.txt")} {
		if obstaja(pot) {
			t.Errorf("vnos je usel iz mape programa: %s", pot)
		}
	}
}

func TestKopirajDatoteko(t *testing.T) {
	mapa := t.TempDir()
	vir, cilj := filepath.Join(mapa, "vir.exe"), filepath.Join(mapa, "cilj", "SafeerOS.exe")
	zapisi(t, vir, "nova razlicica")
	if err := kopirajDatoteko(vir, cilj); err == nil {
		t.Fatal("kopiranje v mapo, ki je ni, bi moralo vrniti napako")
	}
	os.MkdirAll(filepath.Dir(cilj), 0755)
	if err := kopirajDatoteko(vir, cilj); err != nil || vsebina(cilj) != "nova razlicica" {
		t.Fatalf("nova datoteka: %v, %q", err, vsebina(cilj))
	}
	zapisi(t, vir, "se novejsa")
	if err := kopirajDatoteko(vir, cilj); err != nil || vsebina(cilj) != "se novejsa" {
		t.Fatalf("prepis obstojece: %v, %q", err, vsebina(cilj))
	}
	// Vira ni: cilj ostane, kakrsen je bil.
	if err := kopirajDatoteko(filepath.Join(mapa, "ni-ga.exe"), cilj); err == nil || vsebina(cilj) != "se novejsa" {
		t.Fatalf("manjkajoc vir: %v, %q", err, vsebina(cilj))
	}
	if ostalo := imena(t, filepath.Dir(cilj)); ostalo != "SafeerOS.exe" {
		t.Fatalf("ob cilju so ostale zacasne datoteke: %s", ostalo)
	}
}

func TestIzberiZaganjalnik(t *testing.T) {
	koren := t.TempDir()
	stalna := filepath.Join(koren, "SafeerOS", "SafeerOS.exe")
	prenos := filepath.Join(koren, "Prenosi", "SafeerOS-Windows-1.0.36.exe")
	os.MkdirAll(filepath.Dir(stalna), 0755)
	zapisi(t, prenos, "1.0.36")
	preveri := func(opis, selfExe, ime string, razpakirano bool, pricakovanaPot string, pricakovanoKopirano bool, pricakovanaVsebina string) {
		t.Helper()
		pot, kopirano := izberiZaganjalnik(selfExe, stalna, ime, razpakirano)
		if pot != pricakovanaPot || kopirano != pricakovanoKopirano || vsebina(stalna) != pricakovanaVsebina {
			t.Fatalf("%s: pot=%q kopirano=%v stalna=%q", opis, pot, kopirano, vsebina(stalna))
		}
	}
	// Posebno ime brez stalne kopije: kot doslej, zaganjalnik je datoteka, ki tece.
	kontrola := filepath.Join(koren, "Prenosi", "SafeerControl.exe")
	zapisi(t, kontrola, "kontrola")
	preveri("posebno ime, stalne kopije ni", kontrola, "safeercontrol.exe", true, kontrola, false, "<ni>")
	// Prva namestitev iz Prenosov: zaganjalnik se prepise na stalno mesto.
	preveri("prva namestitev", prenos, "safeeros-windows-1.0.36.exe", true, stalna, true, "1.0.36")
	// Isti exe se enkrat (nic novega): stalna kopija ostane, nic se ne kopira.
	preveri("ponoven zagon iz Prenosov", prenos, "safeeros-windows-1.0.36.exe", false, stalna, false, "1.0.36")
	// Zagon s stalnega mesta.
	preveri("zagon s stalnega mesta", stalna, "safeeros.exe", false, stalna, false, "1.0.36")
	preveri("zagon s stalnega mesta, druge crke", strings.ToUpper(stalna), "safeeros.exe", true, stalna, false, "1.0.36")
	// Ista datoteka pod drugim zapisom poti (povezava, kratko ime 8.3): ne kopira se sama nase.
	if povezava := filepath.Join(koren, "povezava.exe"); os.Symlink(stalna, povezava) == nil {
		preveri("zagon prek povezave na stalno mesto", povezava, "safeeros.exe", true, stalna, false, "1.0.36")
		if u := umaknjene(t, filepath.Dir(stalna)); len(u) != 0 {
			t.Fatalf("stalna kopija se je kopirala sama nase: %v", u)
		}
	}
	// Starejsi exe, ki ni nic namestil (namescena razlicica je novejsa), stalne kopije ne prepise.
	star := filepath.Join(koren, "Prenosi", "SafeerOS-Windows-1.0.17.exe")
	zapisi(t, star, "1.0.17")
	preveri("starejsi exe", star, "safeeros-windows-1.0.17.exe", false, stalna, false, "1.0.36")
	// Novejsi exe iz Prenosov je namestil svojo razlicico: stalna kopija dobi njega.
	nov := filepath.Join(koren, "Prenosi", "SafeerOS-Windows-1.0.37.exe")
	zapisi(t, nov, "1.0.37")
	preveri("novejsi exe", nov, "safeeros-windows-1.0.37.exe", true, stalna, true, "1.0.37")
	// Posebno ime ob obstojeci stalni kopiji: se ne kopira, posodobitev in bliznjici pa ostanejo pri stalni.
	preveri("posebno ime ob stalni kopiji", kontrola, "safeercontrol.exe", true, stalna, false, "1.0.37")
	// Stalne kopije ni mogoce zapisati (mape ni): kot doslej.
	brez := filepath.Join(koren, "ni-mape", "SafeerOS.exe")
	if pot, kopirano := izberiZaganjalnik(nov, brez, "safeeros-windows-1.0.37.exe", true); pot != nov || kopirano {
		t.Fatalf("brez mape: pot=%q kopirano=%v", pot, kopirano)
	}
	// Na stalnem mestu je mapa (ne datoteka): ne steje kot zaganjalnik - umakne se in zaganjalnik se namesti.
	mapaNamesto := filepath.Join(koren, "narobe", "SafeerOS.exe")
	os.MkdirAll(mapaNamesto, 0755)
	if pot, kopirano := izberiZaganjalnik(star, mapaNamesto, "safeeros-windows-1.0.17.exe", false); pot != mapaNamesto || !kopirano || vsebina(mapaNamesto) != "1.0.17" {
		t.Fatalf("mapa na stalnem mestu: pot=%q kopirano=%v vsebina=%q", pot, kopirano, vsebina(mapaNamesto))
	}
}

func TestPocistiOstankeZaganjalnika(t *testing.T) {
	mapa := t.TempDir()
	stalna := filepath.Join(mapa, "SafeerOS.exe")
	pred2h := time.Now().Add(-2 * time.Hour)
	for ime, star := range map[string]bool{"SafeerOS.exe": true, "SafeerOS.exe.staro-1": false, "safeeros.exe.staro-22": true,
		"SafeerOS.exe.novo-100": true, "SafeerOS.exe.novo-200": false, "SafeerOS.exe.bak": true, "drugo.exe.staro-1": true} {
		pot := filepath.Join(mapa, ime)
		zapisi(t, pot, "x")
		if star {
			os.Chtimes(pot, pred2h, pred2h)
		}
	}
	os.MkdirAll(filepath.Join(mapa, "SafeerOS.exe.staro-mapa"), 0755)
	if n := pocistiOstankeZaganjalnika(stalna); n != 3 {
		t.Fatalf("pobrisanih %d, pricakovano 3 (ostalo: %s)", n, imena(t, mapa))
	}
	if ostalo := imena(t, mapa); ostalo != "SafeerOS.exe SafeerOS.exe.bak SafeerOS.exe.novo-200 SafeerOS.exe.staro-mapa drugo.exe.staro-1" {
		t.Fatalf("ostalo: %s", ostalo)
	}
	if n := pocistiOstankeZaganjalnika(filepath.Join(mapa, "ni-mape", "SafeerOS.exe")); n != 0 {
		t.Fatalf("mapa, ki je ni: %d", n)
	}
}

// Celoten potek: prva namestitev iz Prenosov, navaden zagon, posodobitev iz programa, star exe, pobrisan prenos.
func TestPripraviZaganjalnik(t *testing.T) {
	koren := t.TempDir()
	app := filepath.Join(koren, "SafeerOS", "app")
	stalna := filepath.Join(koren, "SafeerOS", "SafeerOS.exe")
	posodobitve := filepath.Join(koren, "SafeerOS", "posodobitve")
	start := filepath.Join(koren, "Start", "Safeer OS.lnk")
	prenos := filepath.Join(koren, "Prenosi", "SafeerOS-Windows-1.0.36.exe")
	os.MkdirAll(app, 0755)
	zapisi(t, prenos, "1.0.36")
	type klic struct {
		exe             string
		sveza, premakni bool
	}
	klici := []klic{}
	uredi := func(exe string, sveza, premakni bool) {
		klici = append(klici, klic{exe, sveza, premakni})
		zapisi(t, start, exe) // kot bi vnos v meniju Start nastal
	}
	korak := func(opis, selfExe string, razpakirano bool, pricakovaniKlici int) {
		t.Helper()
		ime := strings.ToLower(filepath.Base(selfExe))
		if pot := pripraviZaganjalnik(selfExe, app, ime, start, razpakirano, uredi); pot != stalna {
			t.Fatalf("%s: zaganjalnik=%q", opis, pot)
		}
		if vsebina(filepath.Join(app, ".zaganjalnik")) != stalna {
			t.Fatalf("%s: .zaganjalnik=%q", opis, vsebina(filepath.Join(app, ".zaganjalnik")))
		}
		if len(klici) != pricakovaniKlici {
			t.Fatalf("%s: klicev urejanja bliznjic %d, pricakovano %d", opis, len(klici), pricakovaniKlici)
		}
	}

	korak("prva namestitev iz Prenosov", prenos, true, 1)
	if k := klici[0]; k.exe != stalna || !k.sveza || !k.premakni || vsebina(stalna) != "1.0.36" {
		t.Fatalf("prva namestitev: %+v, stalna=%q", k, vsebina(stalna))
	}
	korak("navaden zagon s stalnega mesta", stalna, false, 1)
	korak("navaden zagon iz Prenosov", prenos, false, 1)

	// Uporabnik pobrise vnos v meniju Start: ob naslednjem zagonu nastane znova (zivih bliznjic ne preusmerjamo).
	os.Remove(start)
	korak("manjka vnos v meniju Start", stalna, false, 2)
	if k := klici[1]; k.exe != stalna || k.sveza || k.premakni {
		t.Fatalf("manjkajoc vnos: %+v", k)
	}

	// Posodobitev iz programa: preneseni exe je prepisal stalno kopijo in tece z nje; prenos v mapi posodobitve gre.
	zapisi(t, filepath.Join(posodobitve, "SafeerOS-Windows-1.0.37.exe"), "1.0.37")
	zapisi(t, stalna, "1.0.37")
	korak("posodobitev iz programa", stalna, true, 3)
	if k := klici[2]; !k.premakni || obstaja(filepath.Join(posodobitve, "SafeerOS-Windows-1.0.37.exe")) {
		t.Fatalf("posodobitev: %+v, prenos obstaja %v", k, obstaja(filepath.Join(posodobitve, "SafeerOS-Windows-1.0.37.exe")))
	}

	// Posodobitev, pri kateri stalne kopije ni bilo mogoce prepisati: tece preneseni exe iz mape posodobitve.
	prenesen := filepath.Join(posodobitve, "SafeerOS-Windows-1.0.38.exe")
	zapisi(t, prenesen, "1.0.38")
	korak("posodobitev s prenesenim exe", prenesen, true, 4)
	if vsebina(stalna) != "1.0.38" || !obstaja(prenesen) {
		t.Fatalf("stalna=%q, tekoci preneseni exe obstaja %v", vsebina(stalna), obstaja(prenesen))
	}
	korak("zagon po posodobitvi", stalna, false, 4)
	if obstaja(prenesen) {
		t.Fatal("preneseni exe je po naslednjem zagonu ostal v mapi posodobitve")
	}

	// Star exe iz Prenosov (namescena razlicica je novejsa): nic se ne spremeni.
	korak("star exe", prenos, false, 4)
	if vsebina(stalna) != "1.0.38" {
		t.Fatalf("star exe je prepisal stalno kopijo: %q", vsebina(stalna))
	}

	// Zapis .zaganjalnik iz starejse razlicice kaze v Prenose: popravi se in bliznjici se preverita.
	zapisi(t, filepath.Join(app, ".zaganjalnik"), prenos)
	korak("star zapis .zaganjalnik", stalna, false, 5)
	if k := klici[4]; k.exe != stalna || k.sveza || k.premakni {
		t.Fatalf("star zapis: %+v", k)
	}

	// Prvi zagon, ki se je prekinil po razpakiravi (zapisa .zaganjalnik se ni): naslednji zagon je se vedno »svez«
	// (ikona na namizju nastane), ceprav ni nic razpakiral; stalna kopija nastane.
	koren2 := t.TempDir()
	app2 := filepath.Join(koren2, "SafeerOS", "app")
	os.MkdirAll(app2, 0755)
	zapisi(t, filepath.Join(app2, ".version"), "odtis")
	klici = klici[:0]
	if pot := pripraviZaganjalnik(prenos, app2, "safeeros-windows-1.0.36.exe", start, false, uredi); pot != stalnaPot(app2) {
		t.Fatalf("prekinjen prvi zagon: zaganjalnik=%q", pot)
	}
	if len(klici) != 1 || !klici[0].sveza || !klici[0].premakni || vsebina(stalnaPot(app2)) != "1.0.36" {
		t.Fatalf("prekinjen prvi zagon: %+v, stalna=%q", klici, vsebina(stalnaPot(app2)))
	}
}

// Stalna kopija tece (zagon prav v tem trenutku): Windows je ne pusti prepisati, preimenovati pa.
func TestZaganjalnikVRabiSeZamenja(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("datoteka v rabi, ki je ni mogoce prepisati, je posebnost Windows")
	}
	mapa, err := os.MkdirTemp("", "safeer-stalna-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(mapa)
	stalna := filepath.Join(mapa, "SafeerOS.exe")
	jaz, _ := os.Executable()
	podatki, err := os.ReadFile(jaz)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(stalna, podatki, 0755); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(stalna)
	cmd.Env = append(os.Environ(), "SAFEER_PREIZKUS_SPI=1")
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	koncan := false
	defer func() {
		if !koncan {
			cmd.Process.Kill()
			cmd.Wait()
		}
	}()
	time.Sleep(700 * time.Millisecond)

	nov := filepath.Join(mapa, "SafeerOS-Windows-9.9.9.exe")
	zapisi(t, nov, "nova razlicica")
	pot, kopirano := izberiZaganjalnik(nov, stalna, "safeeros-windows-9.9.9.exe", true)
	if pot != stalna || !kopirano || vsebina(stalna) != "nova razlicica" {
		t.Fatalf("pot=%q kopirano=%v stalna=%q (%s)", pot, kopirano, vsebina(stalna), imena(t, mapa))
	}
	// Novejsi Windows zna tekoco datoteko zamenjati tudi neposredno; sicer je stara kopija umaknjena (najvec ena).
	pred := umaknjene(t, mapa)
	t.Logf("umaknjene kopije po zamenjavi: %v", pred)
	if len(pred) > 1 {
		t.Fatalf("prevec umaknjenih kopij: %v", pred)
	}
	// Dokler stara kopija tece, umaknjena ostane; po njenem koncu jo naslednji zagon pobrise.
	pocistiOstankeZaganjalnika(stalna)
	if u := umaknjene(t, mapa); len(u) != len(pred) {
		t.Fatalf("kopija v rabi je izginila: %v", u)
	}
	cmd.Process.Kill()
	cmd.Wait()
	koncan = true
	time.Sleep(300 * time.Millisecond)
	pocistiOstankeZaganjalnika(stalna)
	if ostalo := imena(t, mapa); ostalo != "SafeerOS-Windows-9.9.9.exe SafeerOS.exe" {
		t.Fatalf("ostalo: %s", ostalo)
	}
}

// ---------------------------------------------------------------------------------------------------------------
// Zagon programa: knjiznice preveri program sam (krog 105).

// izhodSKodo vrne napako pravega podprocesa, ki se je koncal s to kodo (nil pri kodi 0).
func izhodSKodo(t *testing.T, koda int) error {
	t.Helper()
	jaz, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(jaz)
	cmd.Env = append(os.Environ(), fmt.Sprintf("SAFEER_PREIZKUS_KODA=%d", koda))
	return cmd.Run()
}

func TestKodaIzhoda(t *testing.T) {
	if k := kodaIzhoda(nil); k != 0 {
		t.Errorf("brez napake: %d", k)
	}
	if k := kodaIzhoda(errors.New("ni izhodna koda")); k != -1 {
		t.Errorf("druga napaka: %d", k)
	}
	for _, koda := range []int{1, kodaManjkajoKnjiznice} {
		if k := kodaIzhoda(izhodSKodo(t, koda)); k != koda {
			t.Errorf("podproces s kodo %d: %d", koda, k)
		}
	}
	if err := izhodSKodo(t, 0); err != nil {
		t.Errorf("podproces s kodo 0: %v", err)
	}
}

func koncan(err error, po time.Duration) <-chan error {
	c := make(chan error, 1)
	go func() {
		time.Sleep(po)
		c <- err
	}()
	return c
}

func TestPocakajNaZagon(t *testing.T) {
	dnevnik := filepath.Join(t.TempDir(), "safeer_os.log")
	tece := make(chan error) // program, ki se ne konca
	meri := func(opis string, konec <-chan error, cakaOznako bool, najmanj, najdlje time.Duration, pricakovano int, vsaj time.Duration) error {
		t.Helper()
		zacetek := time.Now()
		stanje, err := pocakajNaZagon(konec, dnevnik, cakaOznako, najmanj, najdlje)
		if trajalo := time.Since(zacetek); stanje != pricakovano || trajalo < vsaj || trajalo > vsaj+4*time.Second {
			t.Fatalf("%s: stanje=%d (pricakovano %d), trajalo %v (vsaj %v)", opis, stanje, pricakovano, trajalo, vsaj)
		}
		return err
	}

	// Oznaka pride cez 250 ms: program zazivi, a ne pred `najmanj`.
	os.WriteFile(dnevnik, []byte("prva vrstica\n"), 0644)
	go func() {
		time.Sleep(250 * time.Millisecond)
		os.WriteFile(dnevnik, []byte("prva vrstica\n"+oznakaKnjizniceOK+"\n"), 0644)
	}()
	meri("oznaka med cakanjem", tece, true, 600*time.Millisecond, 20*time.Second, zagonTece, 600*time.Millisecond)
	// Oznaka je ze tam: po `najmanj`.
	meri("oznaka ze v dnevniku", tece, true, 300*time.Millisecond, 20*time.Second, zagonTece, 300*time.Millisecond)
	// Oznake ni (program brez preverbe): caka do `najdlje`.
	os.WriteFile(dnevnik, []byte("brez oznake\n"), 0644)
	meri("brez oznake", tece, true, 100*time.Millisecond, 700*time.Millisecond, zagonTece, 700*time.Millisecond)
	os.Remove(dnevnik)
	meri("brez dnevnika", tece, true, 100*time.Millisecond, 500*time.Millisecond, zagonTece, 500*time.Millisecond)
	// Zagon brez preverbe: po `najmanj`, oznake ne caka.
	meri("brez preverbe", tece, false, 300*time.Millisecond, 20*time.Second, zagonTece, 300*time.Millisecond)

	// Program se konca: brez napake (okno je prepustil prvemu zagonu), s kodo manjkajocih knjiznic, z drugo napako.
	if err := meri("konec brez napake", koncan(nil, 50*time.Millisecond), true, time.Second, 20*time.Second, zagonTece, 0); err != nil {
		t.Fatalf("konec brez napake: %v", err)
	}
	manjkajo, napaka := izhodSKodo(t, kodaManjkajoKnjiznice), izhodSKodo(t, 1)
	if err := meri("manjkajo knjiznice", koncan(manjkajo, 50*time.Millisecond), true, time.Second, 20*time.Second, zagonManjkajo, 0); err != manjkajo {
		t.Fatalf("manjkajo knjiznice: %v", err)
	}
	if err := meri("druga napaka", koncan(napaka, 50*time.Millisecond), true, time.Second, 20*time.Second, zagonNapaka, 0); err != napaka {
		t.Fatalf("druga napaka: %v", err)
	}
	// Brez narocene preverbe koda 86 ni dogovor, ampak napaka.
	meri("koda 86 brez preverbe", koncan(manjkajo, 50*time.Millisecond), false, time.Second, 20*time.Second, zagonNapaka, 0)
}

func TestZazeniProgram(t *testing.T) {
	dnevnik := filepath.Join(t.TempDir(), "safeer_os.log")
	tece := make(chan error)
	manjkajo, napaka := izhodSKodo(t, kodaManjkajoKnjiznice), izhodSKodo(t, 1)
	type potek struct {
		opis        string
		zagoni      []func() (<-chan error, error) // izid vsakega zagona po vrsti
		namestitev  error
		tece        bool
		preverbe    string // s katerim narocilom je bil program zagnan, npr. "da ne"
		namestitev1 int
		sporocila   []string // zacetki naslovov
		vSporocilu  string
	}
	ziv := func() (<-chan error, error) {
		os.WriteFile(dnevnik, []byte(oznakaKnjizniceOK+"\n"), 0644)
		return tece, nil
	}
	zivBrezOznake := func() (<-chan error, error) { return tece, nil }
	konca := func(err error, izpis string) func() (<-chan error, error) {
		return func() (<-chan error, error) {
			os.WriteFile(dnevnik, []byte(izpis), 0644)
			return koncan(err, 30*time.Millisecond), nil
		}
	}
	neZazene := func() (<-chan error, error) { return nil, errors.New("python.exe ni najden") }
	for _, p := range []potek{
		{opis: "vse na mestu", zagoni: []func() (<-chan error, error){ziv}, tece: true, preverbe: "da"},
		{opis: "manjkajo, namestitev uspe", zagoni: []func() (<-chan error, error){konca(manjkajo, "[SafeerOS] manjkajo knjiznice: av\n"), zivBrezOznake},
			tece: true, preverbe: "da ne", namestitev1: 1},
		{opis: "manjkajo, namestitev ne uspe", zagoni: []func() (<-chan error, error){konca(manjkajo, ""), zivBrezOznake},
			namestitev: errors.New("ni povezave"), tece: true, preverbe: "da ne", namestitev1: 1,
			sporocila: []string{"Safeer OS - Opozorilo"}, vSporocilu: "ni povezave"},
		{opis: "napaka ob zagonu", zagoni: []func() (<-chan error, error){konca(napaka, "Traceback: pokvarjeno\n")},
			preverbe: "da", sporocila: []string{"Safeer OS - Napaka pri zagonu"}, vSporocilu: "Traceback: pokvarjeno"},
		{opis: "napaka brez dnevnika", zagoni: []func() (<-chan error, error){konca(napaka, " \n")},
			preverbe: "da", sporocila: []string{"Safeer OS - Napaka pri zagonu"}, vSporocilu: "exit status 1"},
		{opis: "program se ne zazene", zagoni: []func() (<-chan error, error){neZazene},
			preverbe: "da", sporocila: []string{"Safeer OS - Napaka"}, vSporocilu: "python.exe ni najden"},
		{opis: "po namestitvi pade", zagoni: []func() (<-chan error, error){konca(manjkajo, ""), konca(napaka, "ImportError: av\n")},
			preverbe: "da ne", namestitev1: 1, sporocila: []string{"Safeer OS - Napaka pri zagonu"}, vSporocilu: "ImportError: av"},
		{opis: "po namestitvi se ne zazene", zagoni: []func() (<-chan error, error){konca(manjkajo, ""), neZazene},
			preverbe: "da ne", namestitev1: 1, sporocila: []string{"Safeer OS - Napaka"}, vSporocilu: "python.exe ni najden"},
		{opis: "drugi zagon preda okno prvemu", zagoni: []func() (<-chan error, error){konca(nil, oznakaKnjizniceOK+"\n")}, tece: true, preverbe: "da"},
	} {
		os.Remove(dnevnik)
		preverbe, naslovi, besedila, namestitev := []string{}, []string{}, []string{}, 0
		zazeni := func(preverba bool) (<-chan error, error) {
			preverbe = append(preverbe, map[bool]string{true: "da", false: "ne"}[preverba])
			if len(preverbe) > len(p.zagoni) {
				t.Fatalf("%s: prevec zagonov", p.opis)
			}
			return p.zagoni[len(preverbe)-1]()
		}
		namesti := func() error {
			namestitev++
			return p.namestitev
		}
		sporoci := func(naslov, besedilo string, slog uint) {
			naslovi = append(naslovi, naslov)
			besedila = append(besedila, besedilo)
		}
		izid := zazeniProgram(zazeni, namesti, sporoci, dnevnik, 150*time.Millisecond, 5*time.Second)
		if izid != p.tece || strings.Join(preverbe, " ") != p.preverbe || namestitev != p.namestitev1 || strings.Join(naslovi, "|") != strings.Join(p.sporocila, "|") {
			t.Errorf("%s: tece=%v zagoni=%v namestitev=%d sporocila=%v", p.opis, izid, preverbe, namestitev, naslovi)
		}
		if p.vSporocilu != "" && !strings.Contains(strings.Join(besedila, "\n"), p.vSporocilu) {
			t.Errorf("%s: v sporocilu ni %q: %v", p.opis, p.vSporocilu, besedila)
		}
	}
}

// Odtis paketa iz gradnje (-X main.paketOdtis): zaganjalnik paketa ob navadnem zagonu ne zgosca.
func TestOdtisIzGradnje(t *testing.T) {
	mapa := filepath.Join(t.TempDir(), "app")
	a := paket(t, map[string]string{"windows/VERSION": "1.0.36", "windows/safeer_os_windows.py": "a"})
	b := paket(t, map[string]string{"windows/VERSION": "1.0.36", "windows/safeer_os_windows.py": "b"})
	odtis := strings.Repeat("ab", 32)
	if ok, err := razpakirajZOdtisom(a, odtis, mapa, false); err != nil || !ok {
		t.Fatalf("prva namestitev: %v %v", ok, err)
	}
	if v := vsebina(filepath.Join(mapa, ".version")); v != odtis {
		t.Fatalf("zapis o paketu: %q", v)
	}
	// Isti odtis: paketa se ne dotakne (tudi ce bi bila vsebina druga - odtis je iz gradnje, ne iz zgoscanja).
	if ok, _ := razpakirajZOdtisom(b, odtis, mapa, false); ok || vsebina(filepath.Join(mapa, "windows", "safeer_os_windows.py")) != "a" {
		t.Fatal("paket z istim odtisom se je razpakiral znova")
	}
	// Drug odtis, ista razlicica: nova gradnja se namesti.
	drugi := strings.Repeat("cd", 32)
	if ok, _ := razpakirajZOdtisom(b, drugi, mapa, false); !ok || vsebina(filepath.Join(mapa, "windows", "safeer_os_windows.py")) != "b" {
		t.Fatal("nova gradnja iste razlicice se ni namestila")
	}
	// Prazen ali nepravilen odtis: izracuna se iz paketa (razvojna gradnja) - isti kot pri razpakiraj().
	for _, slab := range []string{"", "abc", strings.Repeat("AB", 32), strings.Repeat("zz", 32)} {
		mapa2 := filepath.Join(t.TempDir(), "app")
		if ok, err := razpakirajZOdtisom(a, slab, mapa2, false); err != nil || !ok {
			t.Fatalf("odtis %q: %v %v", slab, ok, err)
		}
		pravi := vsebina(filepath.Join(mapa2, ".version"))
		if !jeOdtis(pravi) || pravi == slab {
			t.Fatalf("odtis %q: v zapisu je %q", slab, pravi)
		}
		if ok, _ := razpakiraj(a, mapa2, false); ok {
			t.Fatalf("odtis %q: razpakiraj() ne prepozna istega paketa", slab)
		}
	}
}

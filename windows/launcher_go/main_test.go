package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
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

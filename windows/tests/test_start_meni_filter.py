from safeer_windows import os_backend_win as ob


def test_pomozni_vnosi_menija_start_niso_programi():
    for ime in ("Uninstall Dsj3", "Dsj3 Setup", "Poweriso Help", "Eos Utility Readme",
                "Python 3.14 Manuals", "What Is New In The Latest Version", "Dsj3 Registration"):
        assert ob._ni_program(ime), ime


def test_pravi_programi_ostanejo():
    for ime in ("Paint", "Winrar", "Word 2016", "Safeer OS", "Notepad", "Deluxe Ski Jump 4"):
        assert not ob._ni_program(ime), ime

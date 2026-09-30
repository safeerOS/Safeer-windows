import sys

# libmpv (pravilo 6): runtime iz paketa vendor/mpv/runtime se mora v proces naloziti PRED PySide6,
# sicer Qt vlece sistemski/starejsi msvcp140 in libmpv se lahko sesuje. Brez paketa je to no-op.
if sys.platform == "win32":
    try:
        from safeer_windows.safeer_mpv_pogon import predpripravi_runtime
        predpripravi_runtime()
    except Exception:
        pass

if "--predvajalnik" in sys.argv:
    sys.argv.remove("--predvajalnik")
    from safeer_windows.safeer_predvajalnik import main as predvajalnik_main
    sys.exit(predvajalnik_main())
elif "--os" in sys.argv:
    sys.argv.remove("--os")
    from safeer_windows.os_app import main as os_main
    sys.exit(os_main())
else:
    from safeer_windows.browser import main
    sys.exit(main())

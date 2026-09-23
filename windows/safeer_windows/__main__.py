import sys

if "--os" in sys.argv:
    sys.argv.remove("--os")
    from safeer_windows.os_app import main as os_main
    sys.exit(os_main())
else:
    from safeer_windows.browser import main
    sys.exit(main())

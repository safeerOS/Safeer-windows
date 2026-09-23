import subprocess
r = subprocess.run(["grep", "-rn", "SafeerControlWindow(", "windows/"], capture_output=True, text=True)
print(r.stdout)
print(r.stderr)

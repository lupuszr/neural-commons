"""Apply the narrowly scoped upstream opaque-source read fix in the isolated checkout."""
import pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
PATCH=ROOT/'patches/dkg-opaque-source-read.patch'
def installed(source):
    return subprocess.run(['git','apply','--reverse','--check',str(PATCH)],cwd=source,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
def remove(source):
    if installed(source):subprocess.run(['git','apply','--reverse',str(PATCH)],cwd=source,check=True)
def apply(source):
    if installed(source):return
    subprocess.run(['git','apply','--check',str(PATCH)],cwd=source,check=True)
    subprocess.run(['git','apply',str(PATCH)],cwd=source,check=True)

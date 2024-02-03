pwd
dirpwd=$(pwd)
echo "DIRPWD HERE:"
echo $dirpwd

sdir=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
mkdir -p $sdir/../deps
cd $sdir/../deps
echo "DIRPWD HERE:"
echo $dirpwd

if ! command -v stack &> /dev/null
then
    curl -sSL https://get.haskellstack.org/ | sh
fi
git clone https://github.com/zachjs/sv2v.git
cd sv2v
echo "DIRPWD HERE:"
echo $dirpwd
make
if grep -q docker /proc/1/cgroup; then 
    stack install --local-bin-path /bin/
else
    stack install 
fi
echo "DIRPWD HERE:"
echo $dirpwd
cd $dirpwd
pwd
ls -al

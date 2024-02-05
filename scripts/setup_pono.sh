pip install Cython==0.29 pytest toml scikit-build==0.13.0
if ! command -v sudo &> /dev/null
then
    apt-get update && apt-get install -y flex
fi
    sudo apt-get update && apt-get install -y flex

dirpwd=$(pwd)

sdir=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
mkdir -p cd $sdir/../deps
cd $sdir/../deps

git clone https://github.com/stanford-centaur/pono
cd pono

./contrib/setup-bison.sh
./contrib/setup-btor2tools.sh

./configure.sh --python 
cd build && make -j4 && pip install -e ./python 

cd $dirpwd
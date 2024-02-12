if ! command -v sudo &> /dev/null
then
    apt-get update && apt-get install -y flex
fi
    sudo apt-get update && sudo apt-get install -y flex && sudo apt-get install -y m4

dirpwd=$(pwd)

sdir=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
mkdir -p cd $sdir/../deps
cd $sdir/../deps

git clone https://github.com/stanford-centaur/pono
cd pono

./contrib/setup-bison.sh
./contrib/setup-flex.sh
./contrib/setup-btor2tools.sh

./configure.sh --python 
cd build && make -j4 && pip install -e ./python 

cd $dirpwd

dirpwd=$(pwd)
if ! command -v sudo &> /dev/null
then
    apt install build-essential clang bison flex \
	libreadline-dev gawk tcl-dev libffi-dev git \
	graphviz xdot pkg-config python3 libboost-system-dev \
	libboost-python-dev libboost-filesystem-dev zlib1g-dev -y
fi
	sudo apt install build-essential clang bison flex \
	libreadline-dev gawk tcl-dev libffi-dev git \
	graphviz xdot pkg-config python3 libboost-system-dev \
	libboost-python-dev libboost-filesystem-dev zlib1g-dev -y

sdir=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
mkdir -p cd $sdir/../deps
cd $sdir/../deps

git clone https://github.com/YosysHQ/yosys.git
cd yosys

make config-gcc
make -j4

cp yosys /usr/local/bin
cd $dirpwd

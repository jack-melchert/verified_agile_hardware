pip install Cython==0.29 pytest toml scikit-build==0.13.0

if ! command -v sudo &> /dev/null
then
    apt-get update && apt-get install -y flex
fi
    sudo apt-get update && apt-get install -y flex
    
./contrib/setup-bison.sh
./scripts/setup-smt-switch.sh --python
./contrib/setup-btor2tools.sh

cd /aha/pono && ./configure.sh --python && \
cd /aha/pono/build && make -j4 && pip install -e ./python && \
cd /aha && \
source /aha/bin/activate && \
pip install -e ./pono/deps/smt-switch/build/python && \
pip install -e pono/build/python/
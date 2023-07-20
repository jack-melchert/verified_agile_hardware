dir=$pwd
sdir=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
mkdir -p $sdir/../deps
cd $sdir/../deps
if ! command -v stack &> /dev/null
then
    curl -sSL https://get.haskellstack.org/ | sh
fi
git clone https://github.com/zachjs/sv2v.git
cd sv2v
make
stack install --local-bin-path /bin/
cd $dir

dir=$pwd
sdir=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
mkdir -p $sdir/../deps
cd $sdir/../deps
curl -sSL https://get.haskellstack.org/ | sh
git clone https://github.com/zachjs/sv2v.git
cd sv2v
make
stack install --local-bin-path /bin/
cd $dir

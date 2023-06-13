dir=$pwd
sdir=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
cd $sdir/../deps
curl -sSL https://get.haskellstack.org/ | sh
git clone https://github.com/zachjs/sv2v.git
cd sv2v
make
export PATH=$PATH:~/.local/bin
stack install
cd $dir

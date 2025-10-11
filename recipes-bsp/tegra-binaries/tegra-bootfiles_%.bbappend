addtask do_install_compulab after do_install
do_install_compulab[depends] += "tegra-bootfiles-compulab:do_install_compulab"

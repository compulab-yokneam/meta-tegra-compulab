# The base recipe already depends on virtual/kernel:do_deploy.  Drop the
# provider-specific dependency injected by meta-balena-jetson so selecting
# linux-yocto does not pull linux-noble-nvidia-tegra into the task graph.
python () {
    if "edgeai-orn" not in (d.getVar("MACHINEOVERRIDES") or "").split(":"):
        return

    dependencies = (d.getVarFlag("do_install", "depends") or "").split()
    dependencies = [dependency for dependency in dependencies
                    if dependency != "linux-noble-nvidia-tegra:do_deploy"]
    d.setVarFlag("do_install", "depends", " ".join(dependencies))
}

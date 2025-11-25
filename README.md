# Quick start

 * pre-requisites
   * set up podman (e.g. `~/.config/containers/storage.conf`)
 * install to venv
   * clone the repo `git clone git@github.com:sliwowitz/codexctl.git`
   * create a venv `mkvirtualenv codexctl`
   * in the venv, install from the repo clone `pip install ./codexctl/`
 * configure codexctl
   * set up codexctl (e.g. `~/.config/codexctl/config.yml`)
 * start a project
   * check paths `codexctl config`
   * copy example project into *User projects root*
   * initialize project
     * generate dockerfile
     * build images
     * initialize ssh keys
     * initialize cache
 * run a project
   * create a task
   * assign task to cli or ui


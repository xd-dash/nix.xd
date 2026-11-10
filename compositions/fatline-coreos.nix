{ system }:
{
  schema = 1;
  inherit system;
  scope = "fatline-arm-vm1";
  sources.agni = {
    repository = "dash-xd/agni";
    revision = "dee1aa14b41e7fe4094d7b007a3ecb702d6f8759";
    flakeDirectory = "local/fatline";
    package = "host-link-vm1";
  };
  placement = {
    name = "vm1";
    kind = "coreos";
    container = "coreos-starwisp";
    sshPort = 2222;
    reusePrimary = true;
  };
  ingress = {
    transport = "ssh-tcp-nginx-unix";
    hostPort = 16379;
    guestProxyPort = 16379;
  };
  storeDomain = "common";
  fullFatlineQualified = false;
}

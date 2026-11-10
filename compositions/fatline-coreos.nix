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
  guestAdapter = {
    repository = "dash-xd/agni";
    revision = "de1086a0ab9f6bf412c2b9788b04dc2cafc4b251";
    sha256 = "8b763250cc1e35b761d069be814e1354dbcabaf0a8eb12c98ba7a825adf09a5b";
    contract = "fatline-host-link-v1";
    compatibleRuntimeRevision = "dee1aa14b41e7fe4094d7b007a3ecb702d6f8759";
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

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
  services = {
    repository = "dash-xd/agni";
    revision = "28465d99258c972abe29cad21eebef327a623415";
    refreshFrom = [ "1608001b6fb1c57ad7481b7786c5a9a5e3c4932f" ];
    package = "coreos-services-vm1";
    contract = "coreos-services-v1";
  };
  servicesProbe = {
    repository = "dash-xd/agni";
    revision = "b801e613a35d8eacd3cc7ca9cf469c0b084e4cf7";
    package = "coreos-services-vm1";
    contract = "coreos-services-v1";
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

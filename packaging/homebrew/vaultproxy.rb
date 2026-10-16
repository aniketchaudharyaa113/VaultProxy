class Vaultproxy < Formula
  include Language::Python::Virtualenv

  desc "Local-first, OpenAI-compatible privacy proxy for LLM apps with leak prevention"
  homepage "https://github.com/aniketchaudharyaa113/vaultproxy"
  url "https://github.com/aniketchaudharyaa113/vaultproxy/archive/refs/tags/v0.2.1.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"
  head "https://github.com/aniketchaudharyaa113/vaultproxy.git", branch: "main"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  service do
    run [opt_bin/"vaultproxy", "run"]
    keep_alive true
    log_path var/"log/vaultproxy.log"
    error_log_path var/"log/vaultproxy.err.log"
    environment_variables VAULT_PROFILE: "development"
  end

  test do
    system "#{bin}/vaultproxy", "version"
    output = shell_output("#{bin}/vaultproxy check 'DB_PASS=secret123'")
    assert_match "[SECRET_1]", output
  end
end

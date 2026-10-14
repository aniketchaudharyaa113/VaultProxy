Name:           vaultproxy
Version:        0.2.1
Release:        1%{?dist}
Summary:        Local-first, OpenAI-compatible privacy proxy for LLM applications

License:        MIT
URL:            https://github.com/aniketchaudharyaa113/VaultProxy
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-pip
BuildRequires:  python3-wheel
BuildRequires:  systemd-rpm-macros

Requires:       python3 >= 3.10
Requires:       python3-fastapi
Requires:       python3-uvicorn
Requires:       python3-httpx
Requires:       python3-pydantic
Requires:       python3-pydantic-settings
Requires:       python3-pyyaml

%description
VaultProxy is a local-first, OpenAI-compatible privacy proxy for LLM applications.
It intercepts prompt payloads to mask sensitive Indian personal data (Aadhaar, PAN,
mobile, email, IFSC, UPI) and API secrets using deterministic checksum rules before
forwarding upstream, and restores the values in real time on streaming responses.

%prep
%autosetup -n %{name}-%{version}

%build
%py3_build

%install
%py3_install
install -D -m 0644 packaging/systemd/vaultproxy.service %{buildroot}%{_unitdir}/vaultproxy.service
install -D -m 0600 packaging/systemd/config.env %{buildroot}%{_sysconfdir}/vaultproxy/config.env

%post
%systemd_post vaultproxy.service

%preun
%systemd_preun vaultproxy.service

%postun
%systemd_postun_with_restart vaultproxy.service

%files
%license LICENSE
%doc README.md
%{_bindir}/vaultproxy
%{python3_sitelib}/vaultproxy/
%{python3_sitelib}/vaultproxy-*.egg-info/
%{_unitdir}/vaultproxy.service
%config(noreplace) %{_sysconfdir}/vaultproxy/config.env

%changelog
* Wed Oct 14 2026 Aniket Chaudhary <aniketchaudharyaa113@users.noreply.github.com> - 0.2.1-1
- Initial RPM release for VaultProxy

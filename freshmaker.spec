Name:       freshmaker
Version:    0.0.4
Release:    1%{?dist}
Summary:    Freshmaker is a service scheduling rebuilds of artifacts as new content becomes available.

Group:      Development/Tools
License:    MIT
URL:        https://pagure.io/freshmaker
Source0:    https://files.pythonhosted.org/packages/source/o/%{name}/%{name}-%{version}.tar.gz

%if 0%{?rhel} && 0%{?rhel} <= 7
# In EL7 we need flask which needs python-itsdangerous which comes from
# rhel7-extras which is only available on x86_64 for now.
ExclusiveArch: %{ix86} x86_64
%else
BuildArch:    noarch
%endif

BuildRequires:    fedmsg-hub
BuildRequires:    help2man
BuildRequires:    kobo
BuildRequires:    python2-devel
BuildRequires:    python2-flask-migrate
BuildRequires:    python2-funcsigs
BuildRequires:    python2-futures
BuildRequires:    python2-pdc-client
BuildRequires:    python-enum34
BuildRequires:    python-flask-script
BuildRequires:    python-httplib2
BuildRequires:    python-munch

%if 0%{?rhel} && 0%{?rhel} <= 7
BuildRequires:    python-setuptools
BuildRequires:    python-fedora
BuildRequires:    python-flask
BuildRequires:    python-flask-sqlalchemy
BuildRequires:    python-mock
BuildRequires:    python-nose
BuildRequires:    python-psutil
BuildRequires:    python-pytest
BuildRequires:    pyOpenSSL
BuildRequires:    python-six
BuildRequires:    python-sqlalchemy
BuildRequires:    koji
%else
BuildRequires:    python2-setuptools
BuildRequires:    python2-fedora
BuildRequires:    python2-flask
BuildRequires:    python2-flask-sqlalchemy
BuildRequires:    python2-mock
BuildRequires:    python2-nose
BuildRequires:    python2-psutil
BuildRequires:    python2-pytest
BuildRequires:    python2-pyOpenSSL
BuildRequires:    python2-six
BuildRequires:    python2-sqlalchemy
BuildRequires:    python2-koji
%endif

BuildRequires:    systemd
%{?systemd_requires}

Requires:    fedmsg-hub
Requires:    systemd
Requires:    kobo
Requires:    python2-funcsigs
Requires:    python2-futures
Requires:    python2-koji
Requires:    python2-openidc-client
Requires:    python2-pdc-client
Requires:    python-enum34
Requires:    python-flask-script
Requires:    python-httplib2
Requires:    python-munch

%if 0%{?rhel} && 0%{?rhel} <= 7
Requires:    python-fedora
Requires:    python-flask
Requires:    python-flask-migrate
Requires:    python-flask-sqlalchemy
Requires:    python-mock
Requires:    python-psutil
Requires:    pyOpenSSL
Requires:    python-six
Requires:    python-sqlalchemy
%else
Requires:    python2-fedora
Requires:    python2-flask
Requires:    python2-flask-migrate
Requires:    python2-flask-sqlalchemy
Requires:    python2-mock
Requires:    python2-psutil
Requires:    python2-pyOpenSSL
Requires:    python2-six
Requires:    python2-sqlalchemy
Requires:    python2-systemd
%endif

%description
Freshmaker is a service scheduling rebuilds of artifacts as new content becomes available.

%prep
%setup -q


%build
%py2_build


%install
%py2_install

export PYTHONPATH=%{buildroot}%{python2_sitelib}
mkdir -p %{buildroot}%{_mandir}/man1
for command in freshmaker-manager freshmaker-frontend freshmaker-gencert freshmaker-upgradedb ; do
FRESHMAKER_CONFIG_FILE=conf/config.py help2man -N --version-string=%{version} \
    %{buildroot}%{_bindir}/$command > \
    %{buildroot}%{_mandir}/man1/$command.1
done


%check
nosetests-%{python2_version} -v


%files
%doc README.md
%license LICENSE
%{python2_sitelib}/freshmaker*
%{_bindir}/freshmaker-*
%{_mandir}/man1/freshmaker-*.1*
%dir %{_sysconfdir}/freshmaker
%{_sysconfdir}/fedmsg.d/*
%config(noreplace) %{_sysconfdir}/freshmaker/config.py
%exclude %{_sysconfdir}/freshmaker/*.py[co]
%exclude %{_sysconfdir}/fedmsg.d/*.py[co]
%exclude %{python2_sitelib}/conf/


%changelog
* Tue Jul 04 2017 Qixiang Wan <qwan@redhat.com> - 0.0.4-1
- Initial version of spec file

#!/usr/bin/python3
"""Extend the supplied, version-bounded Calamares patch. No disk operations."""
from pathlib import Path
import argparse, shutil, tempfile
import base_patch

EXTRA = ['src/modules/summary/SummaryViewStep.cpp', 'src/modules/summary/SummaryPage.cpp']
BASE = ['src/modules/'+p for p in ['partition/gui/ChoicePage.cpp',
    'partition/core/PartitionCoreModule.cpp', 'partition/PartitionViewStep.cpp',
    'keyboard/KeyboardPage.cpp', 'keyboard/Config.cpp', 'summary/Config.cpp',
    'finished/FinishedPage.cpp']] + ['src/calamares/CalamaresWindow.cpp',
    'src/libcalamaresui/viewpages/ExecutionViewStep.cpp']

def patch(source, header, check_only=False):
    source=Path(source).resolve()
    if not (source/'debian/changelog').read_text().startswith('calamares (3.3.14-1)'):
        raise RuntimeError('Only clean Debian Calamares 3.3.14-1 source is accepted.')
    with tempfile.TemporaryDirectory(prefix='vault-calamares-patch-') as td:
        work=Path(td)
        for rel in BASE+EXTRA+['debian/changelog']:
            out=work/rel; out.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source/rel,out)
        base_patch.patch(work,Path(header).resolve())
        # Compact margins; leave partitioning and job generation untouched.
        for rel in BASE:
            path=work/rel; s=path.read_text()
            for old,new in [
                ('setContentsMargins(110, 0, 110, 0)', 'setContentsMargins(24, 0, 24, 0)'),
                ('setContentsMargins(90, 0, 90, 0)', 'setContentsMargins(24, 0, 24, 0)'),
                ('setContentsMargins( 70, 10, 70, 10 )','setContentsMargins( 16, 8, 16, 8 )'),
                ('setContentsMargins( 120, 36, 120, 36 )','setContentsMargins( 24, 12, 24, 12 )'),
                ('setMinimumHeight(40)', 'setMinimumHeight(30)'),
                ('Erase drive & install','Erase drive and install'),
                ('Restart into Bitcoin Core"','Restart into Bitcoin Core Vault"'),
                ('Restart this computer to boot directly into Bitcoin Core.',
                 'Restart this computer to open Bitcoin Core Vault.'),
                ('Review your choices before installation. Nothing is written to disk until you press Install Bitcoin Core Vault.',
                 'Ready to install. Check the drive, then confirm below.'),
                ('Preparing the selected drive and copying the offline environment.',
                 'Please keep the computer powered on and the installation USB connected.'),
            ]:
                s=s.replace(old,new)
            path.write_text(s)
        # Do not label a failed installation as a restart into an installed Vault.
        path=work/'src/modules/finished/FinishedPage.cpp'
        s=path.read_text()
        s='#include <QCoreApplication>\n#include <QVariant>\n'+s
        s=base_patch.once(s,'    m_failure = !message.isEmpty() ? message : details;',
            '    QCoreApplication::instance()->setProperty("coreVaultInstallationFailed", true);\n'
            '    m_failure = !message.isEmpty() ? message : details;', 'failure state')
        path.write_text(s)
        path=work/'src/calamares/CalamaresWindow.cpp'
        s='#include <QCoreApplication>\n#include <QVariant>\n#include <QTimer>\n'+path.read_text()
        s=base_patch.once(s,'quit->setText(QStringLiteral("Restart into Bitcoin Core Vault"));',
            'quit->setText(QCoreApplication::instance()->property("coreVaultInstallationFailed").toBool() '
            '? QStringLiteral("Close installer") : QStringLiteral("Restart into Bitcoin Core Vault"));', 'failure button')
        s=base_patch.once(s,
            '    QObject::connect(viewManager, &Calamares::ViewManager::currentStepChanged, navigation, updateNavigation);',
            '    QObject::connect(viewManager, &Calamares::ViewManager::currentStepChanged, navigation, '
            '[navigation, updateNavigation]() { updateNavigation(); QTimer::singleShot(0, navigation, updateNavigation); });',
            'deferred navigation refresh')
        path.write_text(s)
        # An explicit acknowledgement is reset each time Review is entered.
        path=work/EXTRA[0];s=path.read_text()
        s=base_patch.once(s,'#include "SummaryPage.h"',
                         '#include "SummaryPage.h"\n#include <QCheckBox>\n#include <QVBoxLayout>', 'summary imports')
        s=base_patch.once(s,'    emit nextStatusChanged( true );',r'''    // CORE_VAULT_CONSENT_V1
    auto* consent = new QCheckBox(
        tr("I understand that everything on the selected drive will be erased."), m_widget);
    consent->setObjectName(QStringLiteral("coreVaultEraseConsent"));
    m_widget->layout()->addWidget(consent);
    connect(consent, &QCheckBox::toggled, this, [this](bool checked) {
        Q_EMIT nextStatusChanged(checked);
    });
    emit nextStatusChanged(false);''','erase acknowledgement')
        s=base_patch.replace_function(s,'SummaryViewStep::isNextEnabled() const',r'''    auto* consent = m_widget->findChild<QCheckBox*>(QStringLiteral("coreVaultEraseConsent"));
    return consent && consent->isChecked();''')
        s=base_patch.once(s,'    m_config->collectSummaries( this, Config::Widgets::Enabled );',r'''    if (auto* consent = m_widget->findChild<QCheckBox*>(QStringLiteral("coreVaultEraseConsent")))
        consent->setChecked(false);
    Q_EMIT nextStatusChanged(false);
    m_config->collectSummaries( this, Config::Widgets::Enabled );''','reset consent')
        path.write_text(s)
        path=work/EXTRA[1];s=path.read_text()
        s=base_patch.once(s,'    ensureSize( this, m_scrollArea, viewstep );',
            '    // CORE_VAULT: fullscreen reviews scroll instead of exceeding the display.\n    if (!Calamares::Branding::instance()->windowExpands())\n        ensureSize( this, m_scrollArea, viewstep );', 'review scroll')
        path.write_text(s)
        # VAULT_VISUAL_POSTPASS_V3
        import visual_polish
        visual_polish.patch_tree(work)
        outputs=BASE+EXTRA+['src/modules/partition/core/CoreOfflineGuard.h']
        if not check_only:
            for rel in outputs:
                (source/rel).write_bytes((work/rel).read_bytes())
    print('VAULT CALAMARES SOURCE '+('CHECK PASSED' if check_only else 'PATCH APPLIED'))

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('source',type=Path)
    a.add_argument('--header',type=Path,default=Path(__file__).with_name('CoreOfflineGuard.h'))
    a.add_argument('--check',action='store_true');o=a.parse_args()
    patch(o.source,o.header,o.check)

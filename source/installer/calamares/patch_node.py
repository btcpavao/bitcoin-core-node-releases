#!/usr/bin/python3
"""Reuse the exact Vault installer patch, adapting only product copy and paths."""
from pathlib import Path
import argparse
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent/'vault'))
import patch_calamares_source as vault
import base_patch

def patch(source):
    vault.patch(source, Path(__file__).resolve().parent/'vault/CoreOfflineGuard.h')
    outputs=vault.BASE+vault.EXTRA+['src/modules/partition/core/CoreOfflineGuard.h']
    for rel in outputs:
        path=source/rel
        text=path.read_text().replace('Bitcoin Core Vault','Bitcoin Core Node')
        text=text.replace('/etc/calamares/branding/core-offline/','/etc/calamares/branding/core-node/')
        text=text.replace('/usr/lib/core-vault-installer/','/usr/lib/core-node-installer/')
        text=text.replace('QStringLiteral("Powered by Debian")',
                          'QStringLiteral("Powered by Debian GNU/Linux")')
        if rel=='src/modules/partition/PartitionViewStep.cpp':
            text=base_patch.once(text,
                'Bitcoin Core Node will be installed as a dedicated offline environment. No username, password, network, or timezone setup is required.',
                'Bitcoin Core Node will be installed on this drive. Networking is enabled. Your blockchain, wallets, settings and saved files remain on disk after restarting.',
                'persistent Node review')
        if rel=='src/modules/keyboard/Config.cpp':
            text=base_patch.once(text,'<b>Keyboard layout</b>','<b>Keyboard Layout</b>',
                                 'single keyboard review heading')
        if rel=='src/modules/summary/SummaryPage.cpp':
            text=base_patch.once(text,
                '        m_layout->addWidget( createTitleLabel( title, titleFont ) );',
                '        // Keyboard already supplies its heading with the selected layout.\n'
                '        if (!text.startsWith(QStringLiteral("<b>Keyboard Layout</b>")))\n'
                '            m_layout->addWidget( createTitleLabel( title, titleFont ) );',
                'remove duplicate keyboard review title')
        path.write_text(text)
    print('NODE CALAMARES SOURCE PATCH APPLIED')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path)
    patch(parser.parse_args().source.resolve())

// SPDX-License-Identifier: GPL-3.0-or-later
// Core Offline integration; read-only validation before upstream disk jobs.
#pragma once
#include "Job.h"
#include <QMap>
#include <QProcess>
#include <QStringList>

static QMap<QString, QByteArray> coreOfflineDiskIdentity;

static QByteArray coreOfflineProbe(const QString& node)
{
    QProcess p;
    p.start(QStringLiteral("/usr/bin/python3"),
            {QStringLiteral("/usr/lib/core-vault-installer/disk_safety.py"),
             QStringLiteral("probe"), node});
    if (!p.waitForStarted(5000) || !p.waitForFinished(15000)) {
        p.kill(); p.waitForFinished(1000); return {};
    }
    if (p.exitStatus() != QProcess::NormalExit || p.exitCode() != 0) return {};
    return p.readAllStandardOutput().trimmed();
}

class CoreOfflineDiskGuard : public Calamares::Job
{
public:
    CoreOfflineDiskGuard(QStringList nodes, bool eraseOnly)
        : m_nodes(nodes), m_eraseOnly(eraseOnly) {
        for (const auto& n : nodes) m_expected[n] = coreOfflineDiskIdentity.value(n);
    }
    QString prettyName() const override { return QStringLiteral("Check the selected installation disk"); }
    QString prettyStatusMessage() const override { return prettyName(); }
    Calamares::JobResult exec() override {
        if (!m_eraseOnly || m_nodes.size() != 1) {
            return Calamares::JobResult::error(QStringLiteral("Installation stopped before partitioning"),
                QStringLiteral("Only one whole-disk erase installation is permitted."));
        }
        const QString n = m_nodes.first();
        const auto current = coreOfflineProbe(n);
        if (current.isEmpty() || m_expected.value(n).isEmpty() || current != m_expected.value(n)) {
            return Calamares::JobResult::error(QStringLiteral("The selected disk is no longer safe to erase"),
                QStringLiteral("No partition jobs were started. The disk changed, is mounted, removable, too small, or could not be identified. Restart the installer and check the disk selection."));
        }
        return Calamares::JobResult::ok();
    }
private:
    QStringList m_nodes;
    bool m_eraseOnly;
    QMap<QString, QByteArray> m_expected;
};

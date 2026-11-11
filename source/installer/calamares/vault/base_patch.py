#!/usr/bin/env python3
"""Apply version-bounded Bitcoin Core Vault installer safety and UX changes."""
from pathlib import Path
import argparse, re, shutil

MARK='CORE_OFFLINE_INTEGRATION'

def once(text, old, new, name):
    if text.count(old) != 1:
        raise RuntimeError(f"{name}: expected exactly one upstream anchor; found {text.count(old)}")
    return text.replace(old, new, 1)

def mask_cpp_noncode(text):
    out=list(text); i=0; n=len(text)
    def blank(a,b):
        for p in range(a,b):
            if text[p] not in '\r\n': out[p]=' '
    while i<n:
        start=i
        if text.startswith('//',i):
            end=text.find('\n',i+2); end=n if end<0 else end; blank(i,end); i=end
        elif text.startswith('/*',i):
            end=text.find('*/',i+2)
            if end<0: raise RuntimeError('Unterminated block comment')
            end+=2; blank(i,end); i=end
        elif text.startswith('R"',i):
            opening=text.find('(',i+2,min(i+19,n))
            if opening<0: raise RuntimeError('Unsupported raw string')
            delim=text[i+2:opening]; closing=')'+delim+'"'; end=text.find(closing,opening+1)
            if end<0: raise RuntimeError('Unterminated raw string')
            end+=len(closing); blank(i,end); i=end
        elif text[i] in ('"',"'"):
            q=text[i]
            if q=="'" and i>0 and i+1<n and text[i-1].isalnum() and text[i+1].isalnum():
                tok=re.search(r"[A-Za-z0-9_']+$",text[:i])
                if tok and tok.group()[0].isdigit(): i+=1; continue
            i+=1
            while i<n:
                if text[i]=='\\': i+=2
                elif text[i]==q: i+=1; break
                elif text[i]=='\n': raise RuntimeError('Unterminated literal')
                else: i+=1
            else: raise RuntimeError('Unterminated literal')
            blank(start,i)
        else: i+=1
    return ''.join(out)

def function_bounds(text, signature):
    masked=mask_cpp_noncode(text)
    pat=r'(?m)^[ \t]*'+re.escape(signature)+r'[ \t\r\n]*\{'
    matches=list(re.finditer(pat,masked))
    if len(matches)!=1:
        raise RuntimeError(f'Expected one definition of {signature}; found {len(matches)}')
    opening=masked.rfind('{',matches[0].start(),matches[0].end())
    depth=0
    for pos in range(opening,len(masked)):
        if masked[pos]=='{': depth+=1
        elif masked[pos]=='}':
            depth-=1
            if depth==0: return matches[0].start(), pos+1, opening
    raise RuntimeError(f'Unbalanced function {signature}')

def append_function(text, signature, addition):
    start,end,opening=function_bounds(text,signature)
    return text[:end-1]+addition+'\n'+text[end-1:]

def replace_function(text, signature, new_body):
    start,end,opening=function_bounds(text,signature)
    prefix=text[start:opening+1]
    return text[:start]+prefix+'\n'+new_body.rstrip()+'\n}'+text[end:]

# VAULT_MENU_PROGRESS_V2
VAULT_PROGRESS_SURFACE = '// CORE_VAULT_EXECUTION_LAYOUT_V2\n// Only widget geometry. No partitioning, cancellation or job state changes.\nclass CoreVaultExecutionSurface final : public QWidget\n{\npublic:\n    using QWidget::QWidget;\n    QWidget* above = nullptr;\n    QProgressBar* progress = nullptr;\n    QWidget* below = nullptr;\n    QTabWidget* logs = nullptr;\n\n    QSize sizeHint() const override { return QSize(820, 320); }\n    QSize minimumSizeHint() const override { return QSize(420, 260); }\n\n    void arrange()\n    {\n        if (!above || !progress || !below || !logs) return;\n        const int contentWidth = qMin(820, qMax(1, width() - 48));\n        const int x = (width() - contentWidth) / 2;\n        auto heightAt = [contentWidth](QWidget* part) {\n            auto* l = part->layout();\n            const int wrapped = l && l->hasHeightForWidth()\n                ? l->totalHeightForWidth(contentWidth) : -1;\n            return qMax(1, wrapped >= 0 ? wrapped : part->sizeHint().height());\n        };\n        const int aboveHeight = heightAt(above);\n        const int belowHeight = heightAt(below);\n        const int barHeight = qMax(22, progress->sizeHint().height());\n        const bool showLogs = !logs->isHidden();\n        const int logReserve = showLogs ? 120 : 0;\n        const int firstCenter = aboveHeight + 16 + barHeight / 2 + 4;\n        const int lastCenter = height() - belowHeight - 12 - barHeight / 2 - 8 - logReserve;\n        // Map the installer WINDOW midpoint, rather than a bottom toolbar,\n        // into the execution page. Header/footer remain independent.\n        const int desiredCenter = mapFrom(window(), window()->rect().center()).y();\n        const int center = lastCenter >= firstCenter\n            ? qBound(firstCenter, desiredCenter, lastCenter) : firstCenter;\n        const int barY = center - barHeight / 2;\n        above->setGeometry(x, barY - 16 - aboveHeight, contentWidth, aboveHeight);\n        progress->setGeometry(x, barY, contentWidth, barHeight);\n        const int belowY = barY + barHeight + 12;\n        below->setGeometry(x, belowY, contentWidth, belowHeight);\n        if (showLogs) {\n            const int logY = belowY + belowHeight + 12;\n            logs->setGeometry(x, logY, contentWidth, qMax(1, height() - logY - 8));\n        }\n    }\nprotected:\n    void resizeEvent(QResizeEvent* event) override\n    {\n        QWidget::resizeEvent(event);\n        arrange();\n    }\n    void showEvent(QShowEvent* event) override\n    {\n        QWidget::showEvent(event);\n        QTimer::singleShot(0, this, [this]() { arrange(); });\n    }\n};\n'
VAULT_EXECUTION_BODY = '    // CORE_VAULT_EXECUTION_LAYOUT_V2\n    m_widget->setObjectName("slideshow");\n    auto* surface = static_cast<CoreVaultExecutionSurface*>(m_widget);\n    m_progressBar->setParent(m_widget);\n    m_progressBar->setObjectName("exec-progress");\n    m_progressBar->setMaximum(10000);\n    m_progressBar->setFormat(QStringLiteral("%p%"));\n    m_progressBar->setAlignment(Qt::AlignCenter);\n\n    auto* progressPanel = new QWidget(m_widget);\n    progressPanel->setObjectName(QStringLiteral("coreOfflineExecutionPanel"));\n    auto* progressLayout = new QVBoxLayout(progressPanel);\n    progressLayout->setContentsMargins(0, 0, 0, 0);\n    progressLayout->setSpacing(12);\n    auto* progressTitle = new QLabel(QStringLiteral("Installing Bitcoin Core Vault"), progressPanel);\n    progressTitle->setObjectName(QStringLiteral("coreOfflineExecutionTitle"));\n    progressTitle->setAlignment(Qt::AlignCenter);\n    progressTitle->setWordWrap(true);\n    progressLayout->addWidget(progressTitle);\n    auto* progressDescription = new QLabel(\n        QStringLiteral("Please keep the computer powered on and the installation USB connected."), progressPanel);\n    progressDescription->setObjectName(QStringLiteral("coreOfflineExecutionDescription"));\n    progressDescription->setAlignment(Qt::AlignCenter);\n    progressDescription->setWordWrap(true);\n    progressLayout->addWidget(progressDescription);\n\n    auto* controls = new QWidget(m_widget);\n    auto* controlsLayout = new QVBoxLayout(controls);\n    controlsLayout->setContentsMargins(0, 0, 0, 0);\n    controlsLayout->setSpacing(10);\n    m_label->setObjectName("exec-message");\n    m_label->setAlignment(Qt::AlignCenter);\n    m_label->setWordWrap(true);\n    m_label->setMinimumHeight(24);\n    controlsLayout->addWidget(m_label);\n    auto* toggleLogAction = new QAction(QStringLiteral("Show technical log"), m_widget);\n    toggleLogAction->setObjectName(QStringLiteral("coreOfflineToggleLogAction"));\n    auto* toggleLogButton = new QToolButton(controls);\n    toggleLogButton->setObjectName(QStringLiteral("coreOfflineToggleLog"));\n    toggleLogButton->setToolButtonStyle(Qt::ToolButtonTextOnly);\n    toggleLogButton->setDefaultAction(toggleLogAction);\n    controlsLayout->addWidget(toggleLogButton, 0, Qt::AlignHCenter);\n    connect(toggleLogAction, &QAction::triggered, this, &ExecutionViewStep::toggleLog);\n\n    // The log can expand below the centered controls. It never removes the\n    // progress bar or its own Hide technical log button from the screen.\n    m_tab_widget->setParent(m_widget);\n    m_tab_widget->addTab(new QWidget, QStringLiteral("Progress"));\n    m_tab_widget->addTab(m_log_widget, QStringLiteral("Log"));\n    m_tab_widget->tabBar()->hide();\n    m_tab_widget->setCurrentIndex(0);\n    m_tab_widget->hide();\n    surface->above = progressPanel;\n    surface->progress = m_progressBar;\n    surface->below = controls;\n    surface->logs = m_tab_widget;\n    QTimer::singleShot(0, m_widget, [surface]() { surface->arrange(); });\n    connect(JobQueue::instance(), &JobQueue::progress, this, &ExecutionViewStep::updateFromJobQueue);\n'
VAULT_TOGGLE_BODY = '    const bool logBecomesVisible = m_tab_widget->currentIndex() == 0;\n    if (logBecomesVisible) m_log_widget->start();\n    else m_log_widget->stop();\n    m_tab_widget->setCurrentIndex(logBecomesVisible ? 1 : 0);\n    m_tab_widget->setVisible(logBecomesVisible);\n    if (auto* action = m_widget->findChild<QAction*>(QStringLiteral("coreOfflineToggleLogAction")))\n        action->setText(logBecomesVisible ? QStringLiteral("Hide technical log") : QStringLiteral("Show technical log"));\n    static_cast<CoreVaultExecutionSurface*>(m_widget)->arrange();\n'

def vault_refine_execution(source):
    source = once(source, 'namespace Calamares\n{',
                  VAULT_PROGRESS_SURFACE+'\nnamespace Calamares\n{', 'centered progress surface')
    source = once(source, '#include <QVBoxLayout>',
                  '#include <QVBoxLayout>\n#include <QResizeEvent>\n#include <QShowEvent>\n#include <QTimer>', 'surface imports')
    source = once(source, 'm_widget( new QWidget )',
                  'm_widget( new CoreVaultExecutionSurface )', 'execution surface type')
    beginning = source.index('    m_widget->setObjectName( "slideshow" );')
    end_anchor = '    connect( JobQueue::instance(), &JobQueue::progress, this, &ExecutionViewStep::updateFromJobQueue );'
    if source.count(end_anchor) != 1:
        raise RuntimeError('Unexpected progress connection in upstream constructor')
    end = source.index(end_anchor, beginning) + len(end_anchor)
    source = source[:beginning] + VAULT_EXECUTION_BODY.rstrip() + source[end:]
    source = replace_function(source, 'ExecutionViewStep::toggleLog()', VAULT_TOGGLE_BODY)
    source = append_function(source,
        'ExecutionViewStep::updateFromJobQueue( qreal percent, const QString& message )',
        '    static_cast<CoreVaultExecutionSurface*>(m_widget)->arrange();')
    return source


def vault_refine_window(source):
    source = once(source, '        } else if (i >= 4) {',
        '        } else if (i == 3) {\n'
        '            back->hide(); next->hide(); quit->hide();\n'
        '        } else if (i >= 4) {', 'hide unavailable execution navigation')
    anchor = '    QObject::connect(viewManager, &Calamares::ViewManager::currentStepChanged, navigation, updateNavigation);'
    source = once(source, anchor, anchor + r'''
    // Later ViewManager visibility signals must not bring back a disabled
    // Cancel button while jobs are running. No enabled state is changed here.
    QObject::connect(viewManager, &Calamares::ViewManager::quitVisibleChanged,
                     navigation, [viewManager, navigation](bool) {
        if (viewManager->currentStepIndex() == 3)
            if (auto* q = navigation->findChild<QPushButton*>(QStringLiteral("view-button-cancel"))) q->hide();
    });
''', 'keep execution Cancel hidden')
    source = once(source, '    contentsLayout->addWidget( m_viewManager->centralWidget() );', r'''
    // Shared, symmetric content column for Keyboard, Disk, Review and Finish.
    auto* pageColumn = m_viewManager->centralWidget();
    pageColumn->setMaximumWidth(960);
    auto* pageRow = new QHBoxLayout;
    pageRow->setContentsMargins(16, 0, 16, 0);
    pageRow->addStretch(1);
    pageRow->addWidget(pageColumn, 1000);
    pageRow->addStretch(1);
    contentsLayout->addLayout(pageRow, 1);''', 'shared centered page column')
    return source


def vault_test_progress_geometry():
    """Compile the exact widget/constructor with a no-job harness in builder.

    Qt is a Calamares build dependency. This test does not instantiate Calamares,
    enumerate disks or run any installation jobs.
    """
    import os, shlex, subprocess, tempfile
    from pathlib import Path
    module = None
    for candidate in ('Qt6Widgets', 'Qt5Widgets'):
        if subprocess.run(['pkg-config', '--exists', candidate]).returncode == 0:
            module = candidate
            break
    if module is None:
        raise RuntimeError('Qt Widgets build files are required for the progress UI test')
    body = once(VAULT_EXECUTION_BODY,
        '    connect(JobQueue::instance(), &JobQueue::progress, this, &ExecutionViewStep::updateFromJobQueue);',
        '    // Geometry harness: no job queue is created.', 'no-job UI harness')
    code = r'''
#include <QApplication>
#include <QAction>
#include <QLabel>
#include <QProgressBar>
#include <QPlainTextEdit>
#include <QTabWidget>
#include <QTabBar>
#include <QToolButton>
#include <QVBoxLayout>
#include <QResizeEvent>
#include <QShowEvent>
#include <QTimer>
#include <iostream>
#include <stdexcept>
''' + VAULT_PROGRESS_SURFACE + r'''
class TestLog : public QPlainTextEdit {
public: void start() {} void stop() {}
};
class ExecutionViewStep : public QObject {
public:
    QWidget* m_widget = new CoreVaultExecutionSurface;
    QProgressBar* m_progressBar = new QProgressBar;
    QLabel* m_label = new QLabel;
    QTabWidget* m_tab_widget = new QTabWidget;
    TestLog* m_log_widget = new TestLog;
    ExecutionViewStep() {
''' + body + r'''
    }
    void toggleLog() {
''' + VAULT_TOGGLE_BODY + r'''
    }
};
static void require(bool ok, const char* text) {
    if (!ok) throw std::runtime_error(text);
}
int main(int argc, char** argv) {
    QApplication app(argc, argv);
    for (const QSize size : { QSize(800,600), QSize(1024,768), QSize(1280,800), QSize(1920,1080) }) {
        QWidget shell;
        shell.setStyleSheet("QLabel {font-size:14px;} QLabel#coreOfflineExecutionTitle {font-size:28px;} QToolButton {padding:8px 14px;} QProgressBar {min-height:22px;}");
        auto* stack = new QVBoxLayout(&shell);
        stack->setContentsMargins(0,0,0,0); stack->setSpacing(0);
        auto* header = new QWidget; header->setFixedHeight(154);
        auto* footer = new QWidget; footer->setFixedHeight(66);
        ExecutionViewStep step;
        stack->addWidget(header);
        stack->addWidget(step.m_widget, 1);
        stack->addWidget(footer);
        shell.resize(size); shell.show();
        app.processEvents(); app.processEvents();
        step.m_label->setText("Copying Bitcoin Core Vault to the selected drive");
        auto* surface = static_cast<CoreVaultExecutionSurface*>(step.m_widget);
        surface->arrange(); app.processEvents();
        QPoint barCenter = step.m_progressBar->mapTo(&shell, step.m_progressBar->rect().center());
        require(qAbs(barCenter.x()-shell.rect().center().x()) <= 2, "Progress bar is not horizontally centered");
        require(qAbs(barCenter.y()-shell.rect().center().y()) <= 2, "Progress bar is not vertically centered");
        auto* toggle = step.m_widget->findChild<QToolButton*>("coreOfflineToggleLog");
        require(toggle != nullptr, "Log control missing");
        auto toggleCenter = toggle->mapTo(&shell, toggle->rect().center());
        require(toggleCenter.y() > barCenter.y(), "Log control is not below progress bar");
        require(qAbs(toggleCenter.x()-barCenter.x()) <= 2, "Log control is not centered");
        require(surface->above->geometry().top() >= 0, "Title clipped");
        require(surface->below->geometry().bottom() < surface->height(), "Controls clipped");
        step.toggleLog(); app.processEvents(); surface->arrange();
        require(step.m_tab_widget->isVisible() && toggle->isVisible(), "Log mode loses its close control");
        require(step.m_tab_widget->geometry().bottom() < surface->height(), "Log extends below execution area");
        step.toggleLog(); app.processEvents(); surface->arrange();
        require(!step.m_tab_widget->isVisible(), "Log cannot be hidden");
        step.m_progressBar->setValue(4200);
        require(step.m_progressBar->value() == 4200, "Progress value altered");
        std::cout << "PASS actual Qt progress widget " << size.width() << "x" << size.height() << std::endl;
        shell.hide();
    }
    std::cout << "VAULT CALAMARES PROGRESS QT GEOMETRY TEST PASSED" << std::endl;
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='vault-progress-ui-') as td:
        path = Path(td)
        (path/'test.cpp').write_text(code)
        flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', module], text=True))
        subprocess.run(['g++', '-std=c++17', '-fPIC', str(path/'test.cpp'), '-o', str(path/'test'), *flags], check=True)
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR='1', QT_AUTO_SCREEN_SCALE_FACTOR='0')
        subprocess.run([str(path/'test')], env=env, check=True, timeout=30)

def patch(src, header, *, check_only=False):
    changelog=(src/'debian/changelog').read_text()
    if not re.match(r'calamares \(3\.3\.14-[^)]*\)',changelog):
        raise RuntimeError('Patch is limited to Debian Calamares 3.3.14')
    rels=[
      'partition/gui/ChoicePage.cpp','partition/core/PartitionCoreModule.cpp',
      'partition/PartitionViewStep.cpp','keyboard/KeyboardPage.cpp','keyboard/Config.cpp',
      'summary/Config.cpp','finished/FinishedPage.cpp']
    paths={r:src/'src/modules'/r for r in rels}
    paths['ui/CalamaresWindow.cpp']=src/'src/calamares/CalamaresWindow.cpp'
    texts={k:p.read_text() for k,p in paths.items()}
    if any(MARK in t for t in texts.values()):
        raise RuntimeError('Source already patched; use a clean Debian source extraction')

    # Disk UI + safety restrictions.
    c=texts['partition/gui/ChoicePage.cpp']
    c=append_function(c,'ChoicePage::setupActions()',r'''
    // CORE_OFFLINE_INTEGRATION: whole-disk erase is the only supported install operation.
    force_uncheck(m_grp, m_replaceButton);
    force_uncheck(m_grp, m_alongsideButton);
    force_uncheck(m_grp, m_somethingElseButton);
''')
    c=once(c,'    return panelWidget;',
           '    panelWidget->hide(); // CORE_OFFLINE_INTEGRATION\n    return panelWidget;','bootloader panel')
    c=once(c,'    updateDeviceStatePreview();\n\n    // Preview setup done.',
           '    m_core->setBootLoaderInstallPath(currd->deviceNode()); // CORE_OFFLINE_INTEGRATION\n'
           '    updateDeviceStatePreview();\n\n    // Preview setup done.','automatic bootloader disk')
    c=once(c,'    setupUi( this );',r'''    setupUi( this );

    // CORE_OFFLINE_INTEGRATION: clear appliance-style disk page copy.
    auto* pageTitle = new QLabel(QStringLiteral("Choose where to install Bitcoin Core Vault"), this);
    pageTitle->setObjectName(QStringLiteral("coreOfflinePageTitle"));
    auto* pageDescription = new QLabel(
        QStringLiteral("Select one internal drive. The selected drive will be completely erased and dedicated to Bitcoin Core Vault."), this);
    pageDescription->setObjectName(QStringLiteral("coreOfflinePageDescription"));
    pageDescription->setWordWrap(true);
    pageTitle->setAlignment(Qt::AlignCenter);
    pageDescription->setAlignment(Qt::AlignCenter);
    m_mainLayout->setContentsMargins(110, 0, 110, 0);
    m_mainLayout->setSpacing(12);
    m_mainLayout->insertWidget(0, pageDescription);
    m_mainLayout->insertWidget(0, pageTitle);''','disk page heading')
    c=once(c,'    BootInfoWidget* bootInfoWidget = new BootInfoWidget( this );',
           '    BootInfoWidget* bootInfoWidget = new BootInfoWidget( this );\n    bootInfoWidget->hide(); // CORE_OFFLINE_INTEGRATION','hide boot mode')
    c=once(c,'    m_deviceInfoWidget = new DeviceInfoWidget;',
           '    m_deviceInfoWidget = new DeviceInfoWidget;\n    m_deviceInfoWidget->hide(); // CORE_OFFLINE_INTEGRATION','hide partition table badge')
    c=once(c,'    m_messageLabel->setWordWrap( true );\n    m_messageLabel->hide();',r'''    m_messageLabel->setWordWrap( true );
    m_messageLabel->hide();

    auto* eraseWarning = new QLabel(
        QStringLiteral("Everything currently stored on the selected drive will be permanently erased."), this);
    eraseWarning->setObjectName(QStringLiteral("coreOfflineEraseWarning"));
    eraseWarning->setWordWrap(true);
    m_mainLayout->insertWidget(3, eraseWarning);

    // Hide Calamares' generic operation chooser and technical before/after partition diagrams.
    m_itemsScrollArea->hide();
    hLine->hide();
    m_previewBeforeLabel->hide();
    m_previewBeforeFrame->hide();
    m_previewAfterLabel->hide();
    m_previewAfterFrame->hide();
    m_selectLabel->hide();''','disk simplified UI')
    c=once(c,'    m_drivesLabel->setText( tr( "Select storage de&vice:", "@label" ) );',
           '    m_drivesLabel->setText( tr( "Installation drive:", "@label" ) );','drive label')
    c=once(c,'        m_config->setInstallChoice( m_config->initialInstallChoice() );\n        checkInstallChoiceRadioButton( m_config->installChoice() );',
           '        m_config->setInstallChoice( InstallChoice::Erase ); // CORE_OFFLINE_INTEGRATION\n        checkInstallChoiceRadioButton( InstallChoice::Erase );','auto erase choice')
    # CORE_VAULT_SIMPLE_DISK_UI_V1
    # Keep the preview objects/models, but never display the technical
    # partition diagrams when the selected drive is refreshed.
    start, end, _ = function_bounds(
        c, 'ChoicePage::updateActionChoicePreview( InstallChoice choice )'
    )
    preview = c[start:end]
    for widget in ('m_previewAfterFrame', 'm_previewAfterLabel'):
        visible = f'{widget}->show();'
        if preview.count(visible) != 2:
            raise RuntimeError(f'Unexpected Calamares preview source: {widget}')
        preview = preview.replace(visible, f'{widget}->hide();')
    c = c[:start] + preview + c[end:]
    texts['partition/gui/ChoicePage.cpp']=c

    # Disk target filtering and pre-write revalidation.
    c=texts['partition/core/PartitionCoreModule.cpp']
    c=once(c,'#include "core/PartitionCoreModule.h"',
           '#include "core/PartitionCoreModule.h"\n#include "CoreOfflineGuard.h"','guard include')
    c=once(c,'    DeviceList devices = PartUtils::getDevices( PartUtils::DeviceType::WritableOnly );',r'''    // CORE_OFFLINE_INTEGRATION: omit unsafe targets from the drive selector.
    DeviceList detected = PartUtils::getDevices( PartUtils::DeviceType::WritableOnly );
    DeviceList devices;
    coreOfflineDiskIdentity.clear();
    for (auto* d : detected) {
        if (!d) continue;
        const auto identity = coreOfflineProbe(d->deviceNode());
        if (!identity.isEmpty()) {
            devices.append(d);
            coreOfflineDiskIdentity[d->deviceNode()] = identity;
        } else {
            delete d;
        }
    }''','device filtering')
    c=once(c,'    Calamares::JobList lst;\n    QList< Device* > devices;',r'''    Calamares::JobList lst;
    QList< Device* > devices;
    // CORE_OFFLINE_INTEGRATION: validate selected disk immediately before writes.
    QStringList dirty;
    for (const auto* info : m_deviceInfos) {
        if (info->isDirty()) dirty.append(info->device->deviceNode());
    }
    lst << Calamares::job_ptr(new CoreOfflineDiskGuard(
        dirty, config->installChoice() == Config::InstallChoice::Erase));''','pre-write disk guard')
    c=once(c,'    m_osproberLines = PartUtils::runOsprober( this->deviceModel() );',
           '    m_osproberLines.clear(); // CORE_OFFLINE_INTEGRATION: whole-disk appliance install only.','disable OS probing')
    texts['partition/core/PartitionCoreModule.cpp']=c

    # Keyboard page: explanatory text and only layout/variant controls.
    c=texts['keyboard/KeyboardPage.cpp']
    c=once(c,'#include <QComboBox>','#include <QComboBox>\n#include <QLabel>','keyboard label include')
    c=once(c,'    ui->setupUi( this );',r'''    ui->setupUi( this );
    // CORE_OFFLINE_INTEGRATION: only layout + variant are user choices.
    ui->label->hide();
    ui->physicalModelSelector->hide();
    ui->buttonRestore->hide();
    ui->label_2->hide();
    ui->groupSelector->hide();

    auto* pageTitle = new QLabel(QStringLiteral("Choose your keyboard layout"), this);
    pageTitle->setObjectName(QStringLiteral("coreOfflinePageTitle"));
    auto* pageDescription = new QLabel(
        QStringLiteral("Bitcoin Core Vault and the installer stay in English. Choose only how your physical keyboard should behave."), this);
    pageDescription->setObjectName(QStringLiteral("coreOfflinePageDescription"));
    pageDescription->setWordWrap(true);
    pageTitle->setAlignment(Qt::AlignHCenter | Qt::AlignVCenter);
    pageDescription->setAlignment(Qt::AlignHCenter | Qt::AlignVCenter);
    pageTitle->setMargin(0);
    pageDescription->setMargin(0);
    ui->verticalLayout->setContentsMargins(90, 0, 90, 0);
    ui->verticalLayout->setSpacing(10);
    ui->verticalLayout->insertWidget(0, pageDescription);
    ui->verticalLayout->insertWidget(0, pageTitle);

    auto* headings = new QHBoxLayout;
    auto* layoutHeading = new QLabel(QStringLiteral("Keyboard layout"), this);
    auto* variantHeading = new QLabel(QStringLiteral("Variant"), this);
    layoutHeading->setObjectName(QStringLiteral("coreOfflineFieldLabel"));
    variantHeading->setObjectName(QStringLiteral("coreOfflineFieldLabel"));
    headings->addWidget(layoutHeading, 1);
    headings->addWidget(variantHeading, 1);
    ui->verticalLayout->insertLayout(2, headings);
    ui->LE_TestKeyboard->setPlaceholderText(QStringLiteral("Type here to test your keyboard"));''','keyboard page heading')
    c=once(c,'    ui->KBPreviewLayout->addWidget( m_keyboardPreview );',
           '    ui->KBPreviewLayout->addWidget( m_keyboardPreview );\n    m_keyboardPreview->hide(); // CORE_OFFLINE_INTEGRATION','hide keyboard preview')
    texts['keyboard/KeyboardPage.cpp']=c

    # Cleaner keyboard summary.
    c=texts['keyboard/Config.cpp']
    c=replace_function(c,'Config::prettyStatus() const',r'''    QString layout = m_keyboardLayoutsModel->item( m_keyboardLayoutsModel->currentIndex() ).second.description;
    QString variant = m_keyboardVariantsModel->currentIndex() >= 0
        ? m_keyboardVariantsModel->label( m_keyboardVariantsModel->currentIndex() )
        : QStringLiteral("Default");
    return tr( "<b>Keyboard layout</b><br/>%1 · %2", "@label" ).arg( layout, variant );''')
    texts['keyboard/Config.cpp']=c

    # Plain-language disk review instead of raw partition jobs / MSDOS jargon.
    c=texts['partition/PartitionViewStep.cpp']
    c=replace_function(c,'PartitionViewStep::prettyStatus() const',r'''    const QList< PartitionCoreModule::SummaryInfo > list = m_core->createSummaryInfo();
    if ( list.isEmpty() )
    {
        return tr( "No installation drive selected." );
    }
    const auto& info = list.first();
    return tr( "<b>Installation drive</b><br/>%1 <span style='color:#aaaaaa'>(%2)</span><br/><br/>"
               "The selected drive will be completely erased and dedicated to Bitcoin Core Vault." )
        .arg( info.deviceName, info.deviceNode );''')
    c=replace_function(c,'PartitionViewStep::createSummaryWidget() const',r'''    QWidget* widget = new QWidget;
    QVBoxLayout* layout = new QVBoxLayout( widget );
    layout->setContentsMargins( 70, 10, 70, 10 );
    layout->setSpacing( 14 );

    const QList< PartitionCoreModule::SummaryInfo > list = m_core->createSummaryInfo();
    if ( list.isEmpty() )
    {
        auto* missing = new QLabel( tr( "No installation drive selected." ), widget );
        missing->setObjectName( "coreOfflineEraseWarning" );
        layout->addWidget( missing );
        return widget;
    }

    const auto& info = list.first();
    auto* drive = new QLabel(
        tr( "<b>Installation drive</b><br/>%1<br/><span style='color:#aaaaaa'>%2</span>" )
            .arg( info.deviceName, info.deviceNode ), widget );
    drive->setObjectName( "coreOfflineReviewCard" );
    drive->setWordWrap( true );
    layout->addWidget( drive );

    auto* action = new QLabel(
        tr( "<b>What will happen</b><br/>The selected drive will be erased. Bitcoin Core Vault will be installed as a dedicated offline environment. No username, password, network, or timezone setup is required." ), widget );
    action->setObjectName( "coreOfflineReviewCard" );
    action->setWordWrap( true );
    layout->addWidget( action );

    auto* warning = new QLabel(
        tr( "Everything currently stored on this drive will be permanently erased." ), widget );
    warning->setObjectName( "coreOfflineEraseWarning" );
    warning->setWordWrap( true );
    layout->addWidget( warning );

    layout->addStretch();
    return widget;''')
    texts['partition/PartitionViewStep.cpp']=c

    # Review copy.
    c=texts['summary/Config.cpp']
    c=replace_function(c,'Config::retranslate()',r'''    m_title = tr( "Review", "@label" );
    m_message = tr( "Review your choices before installation. Nothing is written to disk until you press Install Bitcoin Core Vault." );
    Q_EMIT titleChanged( m_title );
    Q_EMIT messageChanged( m_message );''')
    texts['summary/Config.cpp']=c

    # Finished page: no Calamares restart checkbox; one clear action in nav.
    c=texts['finished/FinishedPage.cpp']
    c=once(c,'    ui->setupUi( this );',
           '    ui->setupUi( this );\n    ui->restartCheckBox->hide(); // CORE_OFFLINE_INTEGRATION','hide restart checkbox')
    c=once(c,'             [ this ]( Config::RestartMode mode )\n             {\n                 using Mode = Config::RestartMode;\n\n                 ui->restartCheckBox->setVisible( mode != Mode::Never );\n                 ui->restartCheckBox->setEnabled( mode != Mode::Always );\n             } );','             [ this ]( Config::RestartMode )\n             {\n                 ui->restartCheckBox->hide();\n                 ui->restartCheckBox->setEnabled( false );\n             } );','keep restart checkbox hidden')
    c=replace_function(c,'FinishedPage::retranslate()',r'''    ui->retranslateUi( this );
    if ( !m_failure.has_value() )
    {
        ui->mainText->setText(
            QStringLiteral(
                "<h1>Bitcoin Core Vault is ready.</h1><br/>"
                "The installation completed successfully.<br/>"
                "Restart this computer to boot directly into Bitcoin Core.<br/><br/>"
                "<span style='color:#aaaaaa'>Debian and applications stay installed. Wallets and private session files stay in RAM and disappear after shutdown or restart. Please export verified encrypted backups first.</span>" ) );
    }
    else
    {
        ui->mainText->setText(
            tr( "<h1>Installation failed.</h1><br/>Bitcoin Core Vault was not installed.<br/><br/>%1", "@info" )
                .arg( m_failure.value() ) );
    }''')
    texts['finished/FinishedPage.cpp']=c

    # Global header with 3-step indicator and installer-specific navigation labels.
    c=texts['ui/CalamaresWindow.cpp']
    original_body=c[c.index('    const Calamares::Branding* const branding =',c.index('getWidgetSidebar(')):c.index('static QWidget*\ngetWidgetNavigation(')]
    if not original_body.rstrip().endswith('}'):
        raise RuntimeError('Unexpected sidebar source shape')
    replacement_body=r'''    // CORE_OFFLINE_INTEGRATION: Bitcoin Core Vault product header + three-step installer progress.
    auto* box = new QWidget(parent);
    auto* layout = new QVBoxLayout(box);
    layout->setContentsMargins(16, 6, 16, 6);
    layout->setSpacing(4);

    auto* logo = new QLabel(box);
    logo->setAlignment(Qt::AlignCenter);
    logo->setPixmap(QPixmap("/etc/calamares/branding/core-offline/bitcoin.png").scaled(
        44, 44, Qt::KeepAspectRatio, Qt::SmoothTransformation));
    layout->addWidget(logo);

    auto* title = new QLabel(QStringLiteral("Bitcoin Core Vault"), box);
    title->setAlignment(Qt::AlignCenter);
    title->setObjectName(QStringLiteral("coreOfflineProductTitle"));
    layout->addWidget(title);

    auto* subtitle = new QLabel(QStringLiteral("Installer"), box);
    subtitle->setAlignment(Qt::AlignCenter);
    subtitle->setObjectName(QStringLiteral("coreOfflineProductSubtitle"));
    layout->addWidget(subtitle);

    auto* steps = new QHBoxLayout;
    steps->setContentsMargins(0, 4, 0, 0);
    steps->setSpacing(8);
    auto* step1 = new QLabel(box);
    auto* step2 = new QLabel(box);
    auto* step3 = new QLabel(box);
    auto* sep1 = new QLabel(QStringLiteral("────────"), box);
    auto* sep2 = new QLabel(QStringLiteral("────────"), box);
    for (auto* s : { step1, step2, step3 }) {
        s->setAlignment(Qt::AlignCenter);
        s->setFixedWidth(124);
    }
    for (auto* sep : { sep1, sep2 }) {
        sep->setAlignment(Qt::AlignCenter);
        sep->setFixedWidth(64);
    }
    sep1->setObjectName(QStringLiteral("coreOfflineStepSeparator"));
    sep2->setObjectName(QStringLiteral("coreOfflineStepSeparator"));
    steps->addStretch(); steps->addWidget(step1); steps->addWidget(sep1);
    steps->addWidget(step2); steps->addWidget(sep2); steps->addWidget(step3); steps->addStretch();
    layout->addLayout(steps);

    auto* vm = Calamares::ViewManager::instance();
    auto updateSteps = [vm, step1, step2, step3]() {
        const int current = vm->currentStepIndex();
        auto style = [current](QLabel* label, int index, const QString& name) {
            if (current > index) {
                label->setText(QStringLiteral("✓  ") + name);
                label->setStyleSheet(QStringLiteral("QLabel { color:#ffffff; padding:6px 10px; font-weight:600; }"));
            } else if (current == index) {
                label->setText(QString::number(index + 1) + QStringLiteral("  ") + name);
                label->setStyleSheet(QStringLiteral("QLabel { background:#ffffff; color:#000000; border-radius:13px; padding:6px 12px; font-weight:700; }"));
            } else {
                label->setText(QString::number(index + 1) + QStringLiteral("  ") + name);
                label->setStyleSheet(QStringLiteral("QLabel { color:#777777; padding:6px 10px; }"));
            }
        };
        if (current >= 3) {
            step1->setText(QStringLiteral("✓  Keyboard"));
            step2->setText(QStringLiteral("✓  Disk"));
            step3->setText(QStringLiteral("✓  Review"));
            for (auto* s : { step1, step2, step3 }) {
                s->setStyleSheet(QStringLiteral("QLabel { color:#ffffff; padding:6px 10px; font-weight:600; }"));
            }
        } else {
            style(step1, 0, QStringLiteral("Keyboard"));
            style(step2, 1, QStringLiteral("Disk"));
            style(step3, 2, QStringLiteral("Review"));
        }
    };
    QObject::connect(vm, &Calamares::ViewManager::currentStepChanged, box, updateSteps);
    updateSteps();
    box->setFixedHeight(154);
    return box;
}

'''
    c=once(c,original_body,replacement_body,'branded header and stepper')
    c=once(c,'    navigation->setLayout( bottomLayout );',r'''    // CORE_OFFLINE_INTEGRATION: keep upstream controls, add branded footer and plain-language button labels.
    auto* frame = new QVBoxLayout;
    frame->setContentsMargins(8, 0, 8, 4);
    frame->addLayout(bottomLayout);

    auto* footerLogo = new QLabel(navigation);
    footerLogo->setAlignment(Qt::AlignCenter);
    footerLogo->setPixmap(QPixmap("/etc/calamares/branding/core-offline/debian.png").scaled(
        28, 28, Qt::KeepAspectRatio, Qt::SmoothTransformation));
    frame->addWidget(footerLogo);
    auto* credit = new QLabel(QStringLiteral("Powered by Debian"), navigation);
    credit->setAlignment(Qt::AlignCenter);
    credit->setObjectName(QStringLiteral("coreOfflineDebianCredit"));
    frame->addWidget(credit);
    navigation->setLayout(frame);

    auto updateNavigation = [viewManager, navigation]() {
        auto* back = navigation->findChild<QPushButton*>(QStringLiteral("view-button-back"));
        auto* next = navigation->findChild<QPushButton*>(QStringLiteral("view-button-next"));
        auto* quit = navigation->findChild<QPushButton*>(QStringLiteral("view-button-cancel"));
        if (!back || !next || !quit) return;
        for (auto* button : { back, next, quit }) {
            button->setMinimumWidth(140);
            button->setMinimumHeight(40);
        }
        quit->setStyleSheet(QString());
        const int i = viewManager->currentStepIndex();
        if (i == 0) {
            back->hide(); next->show(); next->setText(QStringLiteral("Continue")); quit->show(); quit->setText(QStringLiteral("Cancel"));
        } else if (i == 1) {
            back->show(); next->show(); next->setText(QStringLiteral("Continue")); quit->show(); quit->setText(QStringLiteral("Cancel"));
        } else if (i == 2) {
            back->show(); next->show(); next->setText(QStringLiteral("Erase drive & install")); quit->show(); quit->setText(QStringLiteral("Cancel"));
        } else if (i >= 4) {
            back->hide();
            next->hide();
            quit->show();
            quit->setText(QStringLiteral("Restart into Bitcoin Core"));
            quit->setMinimumWidth(220);
            quit->setStyleSheet(QStringLiteral(
                "QPushButton { background:#ffffff; color:#000000; border:1px solid #ffffff; "
                "border-radius:6px; padding:9px 18px; font-weight:600; } "
                "QPushButton:hover { background:#e7e7e7; border-color:#e7e7e7; } "
                "QPushButton:focus { border:2px solid #f7931a; }"));
        }
    };
    QObject::connect(viewManager, &Calamares::ViewManager::currentStepChanged, navigation, updateNavigation);
    QObject::connect(viewManager, &Calamares::ViewManager::nextLabelChanged, navigation, [updateNavigation](const QString&) { updateNavigation(); });
    QObject::connect(viewManager, &Calamares::ViewManager::quitLabelChanged, navigation, [updateNavigation](const QString&) { updateNavigation(); });
    QObject::connect(viewManager, &Calamares::ViewManager::backLabelChanged, navigation, [updateNavigation](const QString&) { updateNavigation(); });
    updateNavigation();''','branded footer/navigation')
    c = vault_refine_window(c)
    texts['ui/CalamaresWindow.cpp']=c


    # CORE_OFFLINE_POLISH_V2: patch the actual execution/progress view.
    execution_path=src/'src/libcalamaresui/viewpages/ExecutionViewStep.cpp'
    execution=execution_path.read_text()
    execution=once(execution,'#include <QPlainTextEdit>\n#include <QProgressBar>','#include <QPlainTextEdit>\n#include <QPixmap>\n#include <QProgressBar>','execution QPixmap include')
    execution=once(execution,'    m_tab_widget->addTab( m_slideshow->widget(), "Slideshow" );','    auto* progressPanel = new QWidget( m_tab_widget );\n    progressPanel->setObjectName( QStringLiteral("coreOfflineExecutionPanel") );\n\n    auto* progressLayout = new QVBoxLayout( progressPanel );\n    progressLayout->setContentsMargins( 120, 36, 120, 36 );\n    progressLayout->setSpacing( 14 );\n    progressLayout->addStretch();\n\n    auto* progressTitle = new QLabel(\n        QStringLiteral("Installing Bitcoin Core Vault"), progressPanel );\n    progressTitle->setObjectName( QStringLiteral("coreOfflineExecutionTitle") );\n    progressTitle->setAlignment( Qt::AlignCenter );\n    progressLayout->addWidget( progressTitle );\n\n    auto* progressDescription = new QLabel(\n        QStringLiteral("Preparing the selected drive and copying the offline environment."),\n        progressPanel );\n    progressDescription->setObjectName( QStringLiteral("coreOfflineExecutionDescription") );\n    progressDescription->setAlignment( Qt::AlignCenter );\n    progressDescription->setWordWrap( true );\n    progressLayout->addWidget( progressDescription );\n\n    auto* progressStages = new QLabel(\n        QStringLiteral(\n            "Preparing the drive   ·   Copying Bitcoin Core Vault   ·   "\n            "Configuring startup   ·   Checking the installation" ),\n        progressPanel );\n    progressStages->setObjectName( QStringLiteral("coreOfflineExecutionStages") );\n    progressStages->setAlignment( Qt::AlignCenter );\n    progressStages->setWordWrap( true );\n    progressLayout->addWidget( progressStages );\n\n    progressLayout->addStretch();\n\n    m_tab_widget->addTab( progressPanel, QStringLiteral("Progress") );','branded execution panel')
    execution=once(execution,'        "Toggle log" );','        "Show technical log" );','technical log wording')
    execution=once(execution,'    auto toggleLogButton = dynamic_cast< QToolButton* >( toolBar->widgetForAction( toggleLogAction ) );\n    connect( toggleLogButton, &QToolButton::clicked, this, &ExecutionViewStep::toggleLog );','    auto toggleLogButton = dynamic_cast< QToolButton* >( toolBar->widgetForAction( toggleLogAction ) );\n    toggleLogAction->setObjectName( QStringLiteral("coreOfflineToggleLogAction") );\n    toggleLogButton->setObjectName( QStringLiteral("coreOfflineToggleLog") );\n    toolBar->setToolButtonStyle( Qt::ToolButtonTextOnly );\n    connect( toggleLogButton, &QToolButton::clicked, this, &ExecutionViewStep::toggleLog );','technical log control')
    execution=once(execution,'    m_slideshow->changeSlideShowState( Slideshow::Start );','    m_slideshow->widget()->hide(); // CORE_OFFLINE_INTEGRATION: branded progress panel replaces slideshow.','disable slideshow canvas')
    execution=once(execution,'    m_tab_widget->setCurrentIndex( logBecomesVisible ? 1 : 0 );','    m_tab_widget->setCurrentIndex( logBecomesVisible ? 1 : 0 );\n    if ( auto* action = m_widget->findChild< QAction* >(\n             QStringLiteral("coreOfflineToggleLogAction") ) )\n    {\n        action->setText(\n            logBecomesVisible\n                ? QStringLiteral("Hide technical log")\n                : QStringLiteral("Show technical log") );\n    }','dynamic technical log wording')
    execution = vault_refine_execution(execution)
    if not check_only:
        execution_path.write_text(execution)

    # Fail closed after all anchors validate.
    if check_only:
        print('BITCOIN CORE OFFLINE INSTALLER UX SOURCE CHECK PASSED')
        return
    for name,p in paths.items(): p.write_text(texts[name])
    shutil.copyfile(header,src/'src/modules/partition/core/CoreOfflineGuard.h')
    print('BITCOIN CORE OFFLINE INSTALLER UX SOURCE PATCH APPLIED')

if __name__=='__main__':
    import sys
    if sys.argv[1:] == ['--ui-self-test']:
        vault_test_progress_geometry()
        raise SystemExit(0)
    a=argparse.ArgumentParser(); a.add_argument('source',type=Path); a.add_argument('--header',type=Path,default=Path(__file__).with_name('CoreOfflineGuard.h')); a.add_argument('--check',action='store_true')
    o=a.parse_args(); patch(o.source,o.header,check_only=o.check)

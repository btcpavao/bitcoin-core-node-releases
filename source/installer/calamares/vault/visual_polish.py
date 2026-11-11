#!/usr/bin/python3
"""Presentation-only post-pass over the existing reviewed Calamares 3.3.14 patch.
The partition engine, guard, job queue, consent and restart signals are retained.
"""
from pathlib import Path
import re
import base_patch

MARK = 'CORE_VAULT_VISUAL_POLISH_V3'

SHELL = r'''
// CORE_VAULT_VISUAL_POLISH_V3
// Header/footer never borrow space from a page. Existing controls keep their signals.
static void coreVaultSizeNavigationSlots(QWidget* navigation,int step);
class CoreVaultWizardSurface final : public QWidget
{
public:
    QWidget *header, *page, *nav, *footer;
    int step = 0;
    CoreVaultWizardSurface(QWidget* parent, QWidget* h, QWidget* p, QWidget* n)
        : QWidget(parent), header(h), page(p), nav(n), footer(new QWidget(this))
    {
        setObjectName(QStringLiteral("coreVaultWizardSurface"));
        for (auto* w : {header, page, nav}) w->setParent(this);
        page->setMinimumSize(0,0);
        if (page->layout()) page->layout()->setSizeConstraint(QLayout::SetNoConstraint);
        auto* f = new QVBoxLayout(footer);
        f->setContentsMargins(0,0,0,0); f->setSpacing(4);
        auto* logo = new QLabel(footer);
        logo->setObjectName(QStringLiteral("coreVaultFooterLogo"));
        logo->setAlignment(Qt::AlignCenter);
        logo->setPixmap(QPixmap("/etc/calamares/branding/core-offline/debian.png")
                        .scaled(40,49,Qt::KeepAspectRatio,Qt::SmoothTransformation));
        f->addWidget(logo);
        auto* text = new QLabel(QStringLiteral("Powered by Debian"),footer);
        text->setObjectName(QStringLiteral("coreOfflineDebianCredit"));
        text->setAlignment(Qt::AlignCenter); f->addWidget(text);
        header->show(); page->show(); nav->show(); footer->show();
    }
    void setStep(int s) { step=s; arrange(); QTimer::singleShot(0,this,[this](){arrange();}); }
    void arrange()
    {
        const bool compact = height()<680;
        // Recompute only presentation when the viewport enters the compact mode.
        // Scoped QSS uses this property to keep the complete Review readable.
        if (!property("coreVaultCompact").isValid()
            || property("coreVaultCompact").toBool()!=compact) {
            setProperty("coreVaultCompact",compact);
            const QString ownSheet=styleSheet();
            setStyleSheet(QStringLiteral(" ")); setStyleSheet(ownSheet);
            // Clear the selector cache on the property-bearing ancestor first.
            style()->unpolish(this); style()->polish(this);
            for (auto* w : findChildren<QWidget*>()) {
                w->style()->unpolish(w); w->style()->polish(w); w->updateGeometry();
            }
        }
        // CORE_VAULT_REGISTERED_PAGE_MARGINS_V4
        // ViewManager assigns style-default margins after module construction.
        // Normalize the registered page here, including Partition's stacked wrapper.
        if (step<=2) {
            // Qt style polishing resets button minimum sizes. Restore the shared slots afterwards.
            coreVaultSizeNavigationSlots(nav,step);
            auto* views=page->findChild<QStackedWidget*>(QStringLiteral("viewManagerStack"));
            if (views && views->currentWidget() && views->currentWidget()->layout())
                views->currentWidget()->layout()->setContentsMargins(0,0,0,0);
        }
        const int edge = compact ? 12 : 22;
        const int hh = compact ? qMax(132,header->minimumSizeHint().height()) : 162;
        const int fh = 70;
        const int cw = qMin(944, qMax(1,width()-2*(compact?20:32)));
        const int x = (width()-cw)/2;
        header->setFixedHeight(hh);
        header->setGeometry(0,edge,width(),hh);
        footer->setGeometry(0,height()-edge-fh,width(),fh);
        const int top = edge+hh+(compact?4:10);
        const int bottom = height()-edge-fh-(compact?4:12);
        const int room = qMax(1,bottom-top);
        if (step==3) {
            nav->hide(); page->setGeometry(x,top,cw,room); return;
        }
        nav->show();
        const int navh=compact?32:34, gap=compact?8:12;
        // The first three pages share one rectangle and one navigation baseline.
        // Short viewports cap the region; their content uses the compact QSS.
        const int wanted=step>=4 ? 190 : 432;
        const int ph=qMin(wanted,qMax(1,room-navh-gap));
        // Forms start below the stepper. The finished message/button are a centered group.
        const int offset=step>=4 ? qMax(0,(room-ph-navh-gap)/2) : 0;
        page->setGeometry(x,top+offset,cw,ph);
        nav->setGeometry(x,top+offset+ph+gap,cw,navh);
    }
protected:
    void resizeEvent(QResizeEvent* e) override { QWidget::resizeEvent(e); arrange(); }
    void showEvent(QShowEvent* e) override {
        QWidget::showEvent(e); QTimer::singleShot(0,this,[this](){arrange();});
    }
};
'''

NAVIGATION = r'''
// Shared slots retain their width when Back is unavailable on Keyboard.
static void coreVaultInstallNavigationSlots(QWidget* navigation, QBoxLayout* row)
{
    auto* back=navigation->findChild<QPushButton*>(QStringLiteral("view-button-back"));
    auto* next=navigation->findChild<QPushButton*>(QStringLiteral("view-button-next"));
    auto* quit=navigation->findChild<QPushButton*>(QStringLiteral("view-button-cancel"));
    if (!back || !next || !quit) return;
    while (auto* item=row->takeAt(0)) delete item; // Controls and their signals survive.
    row->setContentsMargins(0,0,0,0); row->setSpacing(10);
    row->addStretch();
    const char* names[]={"coreVaultBackSlot","coreVaultPrimarySlot","coreVaultCancelSlot"};
    int i=0;
    for (auto* button : {back,next,quit}) {
        auto* slot=new QWidget(navigation);
        slot->setObjectName(QString::fromLatin1(names[i++]));
        slot->setFixedHeight(32);
        auto* layout=new QHBoxLayout(slot);
        layout->setContentsMargins(0,0,0,0); layout->setSpacing(0);
        layout->addWidget(button,0,Qt::AlignCenter);
        row->addWidget(slot,0,Qt::AlignCenter);
    }
    row->addStretch();
}
static void coreVaultSizeNavigationSlots(QWidget* navigation,int step)
{
    auto* back=navigation->findChild<QPushButton*>(QStringLiteral("view-button-back"));
    auto* next=navigation->findChild<QPushButton*>(QStringLiteral("view-button-next"));
    auto* quit=navigation->findChild<QPushButton*>(QStringLiteral("view-button-cancel"));
    auto* backSlot=navigation->findChild<QWidget*>(QStringLiteral("coreVaultBackSlot"));
    auto* primarySlot=navigation->findChild<QWidget*>(QStringLiteral("coreVaultPrimarySlot"));
    auto* cancelSlot=navigation->findChild<QWidget*>(QStringLiteral("coreVaultCancelSlot"));
    if (!back || !next || !quit || !backSlot || !primarySlot || !cancelSlot) return;
    for (auto* button : {back,next,quit}) button->ensurePolished();
    const int primaryWidth=qMax(194,
        next->fontMetrics().horizontalAdvance(QStringLiteral("Erase drive and install"))+30);
    const int quitWidth=step>=4
        ? qMax(104,quit->fontMetrics().horizontalAdvance(quit->text().remove('&'))+30) : 104;
    back->setFixedSize(104,32); next->setFixedSize(primaryWidth,32); quit->setFixedSize(quitWidth,32);
    backSlot->setFixedWidth(104); primarySlot->setFixedWidth(primaryWidth);
    cancelSlot->setFixedWidth(quitWidth);
    backSlot->setVisible(step<=2); primarySlot->setVisible(step<=2);
    cancelSlot->setVisible(step!=3);
}
'''

PROGRESS = r'''
// CORE_VAULT_VISUAL_POLISH_V3_PROGRESS
class CoreVaultExecutionSurface final : public QWidget
{
public:
    using QWidget::QWidget;
    QWidget* above=nullptr;
    QProgressBar* progress=nullptr;
    QSize sizeHint() const override { return QSize(820,180); }
    QSize minimumSizeHint() const override { return QSize(360,140); }
    void arrange() {
        if (!above || !progress) return;
        const int cw=qMin(820,qMax(1,width()-32));
        const int x=(width()-cw)/2;
        auto* l=above->layout();
        const int wh=l && l->hasHeightForWidth() ? l->totalHeightForWidth(cw) : -1;
        const int ah=qMax(1,wh>=0 ? wh : above->sizeHint().height());
        const int bh=24;
        const int desired=mapFrom(window(),window()->rect().center()).y();
        const int lo=ah+16+bh/2;
        const int hi=height()-bh/2-4;
        const int cy=hi>=lo ? qBound(lo,desired,hi) : lo;
        above->setGeometry(x,cy-bh/2-16-ah,cw,ah);
        progress->setGeometry(x,cy-bh/2,cw,bh);
    }
protected:
    void resizeEvent(QResizeEvent* e) override { QWidget::resizeEvent(e); arrange(); }
    void showEvent(QShowEvent* e) override {
        QWidget::showEvent(e); QTimer::singleShot(0,this,[this](){arrange();});
    }
};
'''
PROGRESS_BODY = r'''
    m_widget->setObjectName("slideshow");
    auto* surface=static_cast<CoreVaultExecutionSurface*>(m_widget);
    m_progressBar->setParent(m_widget);
    m_progressBar->setObjectName("exec-progress");
    m_progressBar->setMaximum(10000);
    m_progressBar->setFormat(QStringLiteral("%p%"));
    m_progressBar->setAlignment(Qt::AlignCenter);
    m_progressBar->show();
    auto* above=new QWidget(m_widget);
    auto* l=new QVBoxLayout(above);
    l->setContentsMargins(0,0,0,0); l->setSpacing(12);
    auto* title=new QLabel(QStringLiteral("Installing Bitcoin Core Vault"),above);
    title->setObjectName("coreOfflineExecutionTitle");
    title->setAlignment(Qt::AlignCenter); title->setWordWrap(true);
    auto* description=new QLabel(QStringLiteral(
        "Please keep the computer powered on and the installation USB connected."),above);
    description->setObjectName("coreOfflineExecutionDescription");
    description->setAlignment(Qt::AlignCenter); description->setWordWrap(true);
    l->addWidget(title); l->addWidget(description);
    // Retain upstream diagnostic objects, but do not expose a status/log control in this view.
    m_label->setParent(m_widget); m_label->hide();
    m_tab_widget->setParent(m_widget);
    m_tab_widget->addTab(m_log_widget,QStringLiteral("Log"));
    m_tab_widget->hide();
    surface->above=above; surface->progress=m_progressBar;
    QTimer::singleShot(0,m_widget,[surface](){surface->arrange();});
    connect(JobQueue::instance(), &JobQueue::progress, this, &ExecutionViewStep::updateFromJobQueue);
'''

KEYBOARD = r'''
    // CORE_VAULT_VISUAL_POLISH_V3: preserve selectors/models, rebuild only their layout.
    auto* spare=new QWidget(this); spare->hide();
    auto* spareLayout=new QVBoxLayout(spare);
    while (auto* item=ui->verticalLayout->takeAt(0)) {
        if (auto* nested=item->layout()) {
            nested->setParent(nullptr); spareLayout->addLayout(nested);
        } else { if (auto* w=item->widget()) w->setParent(spare); delete item; }
    }
    ui->label->hide(); ui->physicalModelSelector->hide(); ui->buttonRestore->hide();
    ui->label_2->hide(); ui->groupSelector->hide();
    auto* pageTitle=new QLabel(QStringLiteral("Choose your keyboard layout"),this);
    pageTitle->setObjectName("coreOfflinePageTitle");
    pageTitle->setAlignment(Qt::AlignCenter);
    pageTitle->setFixedHeight(28);
    auto* pageDescription=new QLabel(QStringLiteral(
        "Bitcoin Core Vault and the installer stay in English. Choose your keyboard layout below."),this);
    pageDescription->setObjectName("coreOfflinePageDescription");
    pageDescription->setAlignment(Qt::AlignCenter); pageDescription->setWordWrap(true);
    ui->verticalLayout->setContentsMargins(0,0,0,0);
    ui->verticalLayout->setSpacing(8);
    ui->verticalLayout->addWidget(pageTitle);
    ui->verticalLayout->addWidget(pageDescription);
    auto* grid=new QGridLayout;
    grid->setContentsMargins(0,0,0,0); grid->setHorizontalSpacing(14); grid->setVerticalSpacing(6);
    auto* layoutHeading=new QLabel(QStringLiteral("Keyboard layout"),this);
    auto* variantHeading=new QLabel(QStringLiteral("Variant"),this);
    for (auto* label : {layoutHeading,variantHeading}) {
        label->setObjectName("coreOfflineFieldLabel"); label->setAlignment(Qt::AlignCenter);
        label->setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Fixed);
    }
    grid->addWidget(layoutHeading,0,0); grid->addWidget(variantHeading,0,1);
    ui->layoutSelector->setParent(this); ui->variantSelector->setParent(this);
    ui->layoutSelector->setMinimumSize(0,70); ui->variantSelector->setMinimumSize(0,70);
    grid->addWidget(ui->layoutSelector,1,0); grid->addWidget(ui->variantSelector,1,1);
    grid->setColumnStretch(0,1); grid->setColumnStretch(1,1); grid->setRowStretch(1,1);
    ui->verticalLayout->addLayout(grid,1);
    ui->LE_TestKeyboard->setParent(this);
    ui->LE_TestKeyboard->setPlaceholderText(QStringLiteral("Type here to test your keyboard"));
    ui->LE_TestKeyboard->setFixedHeight(32);
    ui->verticalLayout->addWidget(ui->LE_TestKeyboard);
    ui->layoutSelector->show(); ui->variantSelector->show(); ui->LE_TestKeyboard->show();
'''

FINISHED = r'''
    ui->retranslateUi(this);
    ui->restartCheckBox->hide();
    if (!m_failure.has_value()) {
        ui->mainText->setText(QStringLiteral(
            "<p style='font-size:42px;color:#4caf50;margin:0'>&#10003;</p>"
            "<p style='font-size:28px;font-weight:600;margin-top:8px;margin-bottom:14px'>Bitcoin Core Vault is ready.</p>"
            "<p>The installation completed successfully.<br/>"
            "Restart this computer to open Bitcoin Core Vault.</p>"));
    } else {
        ui->mainText->setText(tr(
            "<h1>Installation failed.</h1><p>Bitcoin Core Vault was not installed.</p><p>%1</p>")
            .arg(m_failure.value().toHtmlEscaped()));
    }
'''


def once(s,a,b,label): return base_patch.once(s,a,b,label)
def cut(s,a,b,replacement,label,include_end=False):
    if s.count(a)!=1 or s.count(b)!=1: raise RuntimeError('Unrecognized '+label+' source')
    first=s.index(a);last=s.index(b,first)+(len(b) if include_end else 0)
    return s[:first]+replacement+s[last:]

def window(s):
    if MARK in s: raise RuntimeError('Visual source was already patched')
    s='#include <QResizeEvent>\n#include <QShowEvent>\n#include <QStyle>\n#include <QStackedWidget>\n'+s
    s=once(s,'static QSize\ndesktopSize( QWidget* w )',SHELL+NAVIGATION+'\nstatic QSize\ndesktopSize( QWidget* w )','shell class')
    # The header is sized by the shared shell, with a protected outer top margin.
    s=once(s,'layout->setContentsMargins(16, 6, 16, 6);','layout->setContentsMargins(16, 0, 16, 0);','header margins')
    s=once(s,'box->setFixedHeight(154);','box->setFixedHeight(162);','header height')
    start='    // CORE_OFFLINE_INTEGRATION: keep upstream controls, add branded footer and plain-language button labels.'
    end='    auto updateNavigation = [viewManager, navigation]() {'
    s=cut(s,start,end,r'''    // CORE_VAULT_VISUAL_POLISH_V4: stable slots; footer is independent.
    coreVaultInstallNavigationSlots(navigation,bottomLayout);
    navigation->setLayout(bottomLayout);

''','navigation/footer')
    s=once(s,'            button->setMinimumWidth(140);\n            button->setMinimumHeight(30);',
        '            button->setMinimumSize(0,0);\n            button->setSizePolicy(QSizePolicy::Fixed,QSizePolicy::Fixed);','button defaults')
    # Keep original finished failure text, enabled state, quit and consent wiring.
    s=once(s,'border-radius:6px; padding:9px 18px; font-weight:600; ',
        'border-radius:6px; padding:0px 12px; font-size:13px; font-weight:600; ','finished button padding')
    start=s.index(end);stop=s.index('    QObject::connect(viewManager,',start)
    fragment=s[start:stop]
    index=fragment.rfind('    };')
    if index<0: raise RuntimeError('Navigation lambda ending missing')
    fragment=fragment[:index]+r'''
        for (auto* button : {back,next,quit}) button->setIcon(QIcon());
        coreVaultSizeNavigationSlots(navigation,i);
'''+fragment[index:]
    s=s[:start]+fragment+s[stop:]
    a='    QBoxLayout* mainLayout = new QHBoxLayout;'
    b='    baseWidget->setLayout( mainLayout );'
    s=cut(s,a,b,r'''    auto* header=getWidgetSidebar(m_debugManager,m_viewManager,baseWidget,Qt::Horizontal,0);
    auto* navigation=getWidgetNavigation(m_debugManager,m_viewManager,baseWidget,Qt::Horizontal,0);
    auto* shell=new CoreVaultWizardSurface(baseWidget,header,m_viewManager->centralWidget(),navigation);
    auto* mainLayout=new QVBoxLayout;
    mainLayout->setContentsMargins(0,0,0,0); mainLayout->setSpacing(0); mainLayout->addWidget(shell);
    m_viewManager->setPanelSides(Qt::Horizontal);
    QObject::connect(m_viewManager,&Calamares::ViewManager::currentStepChanged,shell,
        [this,shell](){shell->setStep(m_viewManager->currentStepIndex());});
    shell->setStep(m_viewManager->currentStepIndex());
    baseWidget->setLayout(mainLayout);''','wizard layout',True)
    return s

def keyboard(s):
    a='    // CORE_OFFLINE_INTEGRATION: only layout + variant are user choices.'
    b='    ui->LE_TestKeyboard->setPlaceholderText(QStringLiteral("Type here to test your keyboard"));'
    s=cut(s,a,b,KEYBOARD,'keyboard layout',True)
    return '#include <QGridLayout>\n#include <QListView>\n#include <QVBoxLayout>\n'+s

def disk(s):
    # CORE_VAULT_DISK_ANCHOR_FIX_V1
    # These constructor-only statements are emitted by base_patch.patch().
    # m_selectLabel->hide() alone also occurs in updateActionChoicePreview().
    # Retain the exact-one-match guard; never choose a match by its position.
    if MARK + ': never distribute spare height between text labels.' in s:
        raise RuntimeError('Compact disk page was already patched')
    anchor = (
        "    // Hide Calamares' generic operation chooser and technical before/after partition diagrams.\n"
        "    m_itemsScrollArea->hide();\n"
        "    hLine->hide();\n"
        "    m_previewBeforeLabel->hide();\n"
        "    m_previewBeforeFrame->hide();\n"
        "    m_previewAfterLabel->hide();\n"
        "    m_previewAfterFrame->hide();\n"
        "    m_selectLabel->hide();"
    )
    addition=r'''
    // CORE_VAULT_VISUAL_POLISH_V3: never distribute spare height between text labels.
    m_mainLayout->setContentsMargins(0,0,0,0);
    m_mainLayout->setSpacing(12); m_mainLayout->setAlignment(Qt::AlignTop);
    for (int i=0;i<m_mainLayout->count();++i) m_mainLayout->setStretch(i,0);
    pageTitle->setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Fixed);
    pageTitle->setFixedHeight(28);
    pageDescription->setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Fixed);
    eraseWarning->setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Fixed);
    m_drivesLayout->setContentsMargins(0,8,0,0);
    m_drivesLayout->setSpacing(12);
    m_rightLayout->setAlignment(Qt::AlignTop);
    for (int i=0;i<m_rightLayout->count();++i) m_rightLayout->setStretch(i,0);
'''
    return once(s,anchor,anchor+addition,'compact disk page')

def summary(s):
    s=once(s,'    label->setMargin( Calamares::defaultFontHeight() / 2 );','    label->setMargin(0);','summary body indentation')
    s=once(s,'    itemBodyLayout->addSpacing( Calamares::defaultFontHeight() * 2 );','    // No additional summary indentation.','summary indent')
    s=once(s,'    itemBodyCoreLayout->addSpacing( Calamares::defaultFontHeight() / 2 );','    itemBodyCoreLayout->setContentsMargins(0,0,0,0);','summary top indent')
    s=once(s,'    const int SECTION_SPACING = 12;','    const int SECTION_SPACING = 6;','summary spacing')
    s=once(s,'    headerLabel->setText( config->message() );',
        '    headerLabel->setAlignment(Qt::AlignCenter);\n'
        '    headerLabel->setFixedHeight(28);\n'
        '    headerLabel->setText( config->message() );','shared review heading slot')
    s=once(s,'    layout->addWidget( headerLabel );',
        '    layout->setSpacing(6);\n    layout->addWidget( headerLabel );','review outer spacing')
    s=once(s,'    m_layout = new QVBoxLayout( m_contentWidget );',
        '    m_layout = new QVBoxLayout( m_contentWidget );\n'
        '    m_layout->setSpacing(4);','review content spacing')
    return s

def finished(s):
    s=base_patch.replace_function(s,'FinishedPage::retranslate()',FINISHED)
    anchor='    ui->setupUi( this );'
    addition=r'''
    // CORE_VAULT_VISUAL_POLISH_V3: text immediately followed by the shared restart row.
    while (auto* item=ui->verticalLayout->takeAt(0)) {
        if (auto* nested=item->layout()) { delete nested; }
        else { delete item; }
    }
    ui->verticalLayout->setContentsMargins(0,0,0,0);
    ui->verticalLayout->setSpacing(0);
    ui->verticalLayout->addWidget(ui->mainText);
    ui->mainText->setAlignment(Qt::AlignCenter);
    ui->mainText->setWordWrap(true);
'''
    return '#include <QVBoxLayout>\n'+once(s,anchor,anchor+addition,'finished layout')

def execution(s):
    a=s.index('// CORE_VAULT_EXECUTION_LAYOUT_V2')
    b=s.index('namespace Calamares\n{',a)
    s=s[:a]+PROGRESS+'\n'+s[b:]
    a='    // CORE_VAULT_EXECUTION_LAYOUT_V2'
    b='    connect(JobQueue::instance(), &JobQueue::progress, this, &ExecutionViewStep::updateFromJobQueue);'
    s=cut(s,a,b,PROGRESS_BODY,'progress constructor',True)
    s=base_patch.replace_function(s,'ExecutionViewStep::toggleLog()',
        '    // The minimal installation screen has no technical-log control.\n    m_tab_widget->hide();')
    return s

def patch_tree(root):
    root=Path(root)
    changes={
        'src/calamares/CalamaresWindow.cpp':window,
        'src/modules/keyboard/KeyboardPage.cpp':keyboard,
        'src/modules/partition/gui/ChoicePage.cpp':disk,
        'src/modules/summary/SummaryPage.cpp':summary,
        'src/modules/finished/FinishedPage.cpp':finished,
        'src/libcalamaresui/viewpages/ExecutionViewStep.cpp':execution,
    }
    planned={r:fn((root/r).read_text()) for r,fn in changes.items()}
    r='src/modules/partition/PartitionViewStep.cpp'
    s=(root/r).read_text().replace('setContentsMargins( 16, 8, 16, 8 )','setContentsMargins(0,0,0,0)')
    # Only compact card gaps in the existing disk summary; retain all copy/widgets.
    a,b,_=base_patch.function_bounds(s,'PartitionViewStep::createSummaryWidget() const')
    part=once(s[a:b],'    layout->setSpacing( 14 );',
        '    layout->setSpacing( 8 );','review card gaps')
    s=s[:a]+part+s[b:]
    # Rename the summary module heading, not its engine or job configuration.
    s=base_patch.replace_function(s,'PartitionViewStep::prettyName() const','    return tr("Disk");')
    planned[r]=s
    for r,s in planned.items(): (root/r).write_text(s)
    print('VAULT INSTALLER VISUAL POLISH V3 C++ APPLIED')


def self_test():
    """Compile actual shared shell/slots with styled pre-install pages and no jobs."""
    import os,shlex,subprocess,tempfile
    qt=next((n for n in ('Qt6Widgets','Qt5Widgets') if subprocess.run(['pkg-config','--exists',n]).returncode==0),None)
    if qt is None: raise RuntimeError('Qt Widgets development package is required for the layout test')
    location=Path(__file__).resolve()
    candidates=[]
    if os.environ.get('VAULT_INSTALLER_TEST_BRANDING'):
        candidates.append(Path(os.environ['VAULT_INSTALLER_TEST_BRANDING']))
    candidates.append(location.parent/'branding')  # Exact assets staged in the builder.
    candidates.extend(parent/'config/includes.chroot/etc/calamares/branding/core-offline'
        for parent in location.parents)
    branding=next((p for p in candidates if (p/'stylesheet.qss').is_file()
        and (p/'checkmark.svg').is_file() and (p/'checkmark.png').is_file()
        and (p/'debian.png').is_file()
        and (p/'bitcoin.png').is_file()),None)
    if branding is None: raise RuntimeError('Stage the runtime branding files for the styled Qt test')
    style=(branding/'stylesheet.qss').read_text().replace(
        '/etc/calamares/branding/core-offline/checkmark.png',str(branding/'checkmark.png'))
    # Geometry is compiled from the actual class; only its guest asset path changes.
    shell_test=SHELL.replace('/etc/calamares/branding/core-offline/debian.png',
        str(branding/'debian.png'))
    code=r'''#include <QApplication>
#include <QLabel>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QGridLayout>
#include <QProgressBar>
#include <QResizeEvent>
#include <QShowEvent>
#include <QTimer>
#include <QPushButton>
#include <QStackedWidget>
#include <QScrollArea>
#include <QScrollBar>
#include <QCheckBox>
#include <QListWidget>
#include <QLineEdit>
#include <QComboBox>
#include <QFile>
#include <QPixmap>
#include <QStyle>
#include <QVariant>
#include <iostream>
#include <stdexcept>
'''+shell_test+NAVIGATION+PROGRESS+r'''
static void require(bool v,const char* message) {if(!v) throw std::runtime_error(message);}
static QLabel* heading(const QString& text,const char* name,QWidget* parent) {
    auto* w=new QLabel(text,parent); w->setObjectName(QString::fromLatin1(name));
    w->setAlignment(Qt::AlignCenter); w->setFixedHeight(28); return w;
}
static QWidget* installerHeader(const QString& branding) {
    auto* box=new QWidget; auto* l=new QVBoxLayout(box);
    l->setContentsMargins(16,0,16,0); l->setSpacing(4);
    auto* logo=new QLabel(box); logo->setAlignment(Qt::AlignCenter);
    logo->setPixmap(QPixmap(branding+"/bitcoin.png").scaled(44,44,Qt::KeepAspectRatio,Qt::SmoothTransformation));
    l->addWidget(logo);
    auto* title=new QLabel("Bitcoin Core Vault",box); title->setObjectName("coreOfflineProductTitle");
    title->setAlignment(Qt::AlignCenter); l->addWidget(title);
    auto* subtitle=new QLabel("Installer",box); subtitle->setObjectName("coreOfflineProductSubtitle");
    subtitle->setAlignment(Qt::AlignCenter); l->addWidget(subtitle);
    auto* steps=new QHBoxLayout; steps->setContentsMargins(0,4,0,0); steps->setSpacing(8);
    steps->addStretch();
    for(int i=0;i<3;++i) {
        if(i) {
            auto* sep=new QLabel("────────",box); sep->setObjectName("coreOfflineStepSeparator");
            sep->setAlignment(Qt::AlignCenter); sep->setFixedWidth(64); steps->addWidget(sep);
        }
        auto* step=new QLabel(i==0 ? "1  Keyboard" : i==1 ? "2  Disk" : "3  Review",box);
        step->setAlignment(Qt::AlignCenter); step->setFixedWidth(124);
        step->setStyleSheet(i==0
            ? "QLabel { background:#ffffff; color:#000000; border-radius:13px; padding:6px 12px; font-weight:700; }"
            : "QLabel { color:#777777; padding:6px 10px; }");
        steps->addWidget(step);
    }
    steps->addStretch(); l->addLayout(steps); return box;
}
static QWidget* keyboardPage() {
    auto* w=new QWidget;
    auto* l=new QVBoxLayout(w); l->setContentsMargins(0,0,0,0); l->setSpacing(8);
    l->addWidget(heading("Choose your keyboard layout","coreOfflinePageTitle",w));
    auto* d=new QLabel("Bitcoin Core Vault and the installer stay in English. Choose your keyboard layout below.",w);
    d->setObjectName("coreOfflinePageDescription"); d->setAlignment(Qt::AlignCenter); d->setWordWrap(true);
    l->addWidget(d);
    auto* grid=new QGridLayout; grid->setContentsMargins(0,0,0,0);
    grid->setHorizontalSpacing(14); grid->setVerticalSpacing(6);
    for(int col=0;col<2;++col) {
        auto* title=new QLabel(col==0 ? "Keyboard layout" : "Variant",w);
        title->setObjectName("coreOfflineFieldLabel"); title->setAlignment(Qt::AlignCenter);
        title->setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Fixed);
        grid->addWidget(title,0,col);
        auto* list=new QListWidget(w); list->setMinimumSize(0,70);
        list->addItem(col==0 ? "Croatian" : "Default"); list->setCurrentRow(0);
        grid->addWidget(list,1,col); grid->setColumnStretch(col,1);
    }
    grid->setRowStretch(1,1); l->addLayout(grid,1);
    auto* entry=new QLineEdit(w); entry->setPlaceholderText("Type here to test your keyboard");
    entry->setFixedHeight(32); l->addWidget(entry); return w;
}
static QWidget* diskPage() {
    auto* w=new QWidget; auto* l=new QVBoxLayout(w);
    l->setContentsMargins(0,0,0,0); l->setSpacing(12); l->setAlignment(Qt::AlignTop);
    l->addWidget(heading("Choose where to install Bitcoin Core Vault","coreOfflinePageTitle",w));
    auto* d=new QLabel("Select one internal drive. The selected drive will be completely erased and dedicated to Bitcoin Core Vault.",w);
    d->setObjectName("coreOfflinePageDescription"); d->setAlignment(Qt::AlignCenter); d->setWordWrap(true);
    d->setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Fixed); l->addWidget(d);
    auto* row=new QHBoxLayout; row->setContentsMargins(0,8,0,0); row->setSpacing(12);
    row->addWidget(new QLabel("Installation drive:",w));
    auto* drive=new QComboBox(w); drive->addItem("vda - 24.00 GiB (/dev/vda)");
    row->addWidget(drive); row->addStretch(); l->addLayout(row);
    auto* warning=new QLabel("Everything currently stored on the selected drive will be permanently erased.",w);
    warning->setObjectName("coreOfflineEraseWarning"); warning->setWordWrap(true);
    warning->setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Fixed); l->addWidget(warning);
    return w;
}
static QWidget* reviewPage(QScrollArea*& scroll) {
    auto* w=new QWidget; w->setObjectName("summaryStep");
    auto* l=new QVBoxLayout(w); l->setContentsMargins(0,0,0,0); l->setSpacing(6);
    l->addWidget(heading("Ready to install. Check the drive, then confirm below.","summaryTitle",w));
    scroll=new QScrollArea(w); scroll->setWidgetResizable(true);
    scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    scroll->setFrameStyle(QFrame::NoFrame); scroll->setContentsMargins(0,0,0,0);
    auto* content=new QWidget; auto* summary=new QVBoxLayout(content);
    summary->setContentsMargins(0,0,0,0); summary->setSpacing(4);
    auto* keyboardTitle=new QLabel("Keyboard",content); keyboardTitle->setObjectName("summaryItemTitle");
    summary->addWidget(keyboardTitle);
    auto* kb=new QLabel("<b>Keyboard layout</b><br/>Croatian · Default",content);
    kb->setObjectName("summaryItemBody"); kb->setMargin(0); summary->addWidget(kb);
    summary->addSpacing(6);
    auto* diskTitle=new QLabel("Disk",content); diskTitle->setObjectName("summaryItemTitle");
    summary->addWidget(diskTitle);
    auto* cards=new QWidget(content); auto* cl=new QVBoxLayout(cards);
    cl->setContentsMargins(0,0,0,0); cl->setSpacing(8);
    auto card=[cards,cl](const QString& text,const char* name) {
        auto* label=new QLabel(text,cards); label->setObjectName(QString::fromLatin1(name));
        label->setWordWrap(true); cl->addWidget(label);
    };
    card("<b>Installation drive</b><br/>vda<br/><span style='color:#aaaaaa'>/dev/vda</span>","coreOfflineReviewCard");
    card("<b>What will happen</b><br/>The selected drive will be erased. Bitcoin Core Vault will be installed as a dedicated offline environment. No username, password, network, or timezone setup is required.","coreOfflineReviewCard");
    card("Everything currently stored on this drive will be permanently erased.","coreOfflineEraseWarning");
    cl->addStretch(); summary->addWidget(cards); summary->addStretch();
    scroll->setWidget(content); l->addWidget(scroll,1);
    auto* consent=new QCheckBox("I understand that everything on the selected drive will be erased.",w);
    consent->setObjectName("coreVaultEraseConsent"); l->addWidget(consent); return w;
}
static QRect relativeRect(QWidget* w,QWidget* root) {
    return QRect(w->mapTo(root,QPoint(0,0)),w->size());
}
int main(int argc,char** argv) {
    QApplication app(argc,argv);
    require(argc==3,"Stylesheet/branding arguments missing"); QFile style(argv[1]);
    require(style.open(QIODevice::ReadOnly),"Cannot open runtime stylesheet");
    app.setStyleSheet(QString::fromUtf8(style.readAll()));
    require(!QPixmap(QString::fromLocal8Bit(argv[2])+"/checkmark.png").isNull(),
        "Native PNG acknowledgement tick cannot be decoded");
    // Cold construction starts in compact mode before the real window is sized.
    // A native navigation update fixes the controls before the later style transition.
    bool coldAll=true;
    for(const QSize sz:{QSize(800,600),QSize(1024,768),QSize(1280,800),QSize(1920,1080)}) {
        QWidget coldOuter; auto* coldLayout=new QVBoxLayout(&coldOuter);
        coldLayout->setContentsMargins(0,0,0,0);
        auto* coldNav=new QWidget; auto* coldRow=new QHBoxLayout;
        auto* coldBack=new QPushButton("Back",coldNav); coldBack->setObjectName("view-button-back"); coldRow->addWidget(coldBack);
        auto* coldNext=new QPushButton("Continue",coldNav); coldNext->setObjectName("view-button-next"); coldRow->addWidget(coldNext);
        auto* coldCancel=new QPushButton("Cancel",coldNav); coldCancel->setObjectName("view-button-cancel"); coldRow->addWidget(coldCancel);
        coreVaultInstallNavigationSlots(coldNav,coldRow); coldNav->setLayout(coldRow);
        coreVaultSizeNavigationSlots(coldNav,0);
        auto* coldShell=new CoreVaultWizardSurface(&coldOuter,new QWidget,new QWidget,coldNav);
        coldShell->setStep(0);
        require(coldShell->property("coreVaultCompact").toBool(),"Cold constructor is not compact");
        // Match updateNavigation's presentation operations after constructor polish.
        for(auto* button:{coldBack,coldNext,coldCancel}) {
            button->setMinimumSize(0,0); button->setSizePolicy(QSizePolicy::Fixed,QSizePolicy::Fixed);
            button->setIcon(QIcon());
        }
        coldCancel->setStyleSheet(QString()); coldBack->hide();
        coreVaultSizeNavigationSlots(coldNav,0);
        coldLayout->addWidget(coldShell); coldOuter.resize(sz); coldOuter.show();
        app.processEvents(); app.processEvents(); coldShell->arrange(); app.processEvents();
        const bool valid=coldNext->size()==QSize(194,32) && coldCancel->size()==QSize(104,32)
            && coldNext->minimumSize()==QSize(194,32) && coldCancel->minimumSize()==QSize(104,32);
        coldAll=coldAll && valid;
        std::cout<<"Cold native navigation "<<sz.width()<<"x"<<sz.height()
            <<" compact="<<coldShell->property("coreVaultCompact").toBool()
            <<" next="<<coldNext->width()<<"x"<<coldNext->height()
            <<" cancel="<<coldCancel->width()<<"x"<<coldCancel->height()
            <<" nextMinimum="<<coldNext->minimumWidth()<<"x"<<coldNext->minimumHeight()
            <<" cancelMinimum="<<coldCancel->minimumWidth()<<"x"<<coldCancel->minimumHeight()
            <<" result="<<(valid?"PASS":"FAIL")<<std::endl;
        for(const QSize transition:{QSize(800,600),QSize(1280,800),sz}) {
            coldOuter.resize(transition); app.processEvents(); app.processEvents();
            coldShell->arrange(); app.processEvents();
            const bool retained=coldNext->size()==QSize(194,32) && coldCancel->size()==QSize(104,32);
            coldAll=coldAll && retained;
            std::cout<<"Retained native navigation "<<sz.width()<<"x"<<sz.height()
                <<" -> "<<transition.width()<<"x"<<transition.height()
                <<" next="<<coldNext->width()<<"x"<<coldNext->height()
                <<" cancel="<<coldCancel->width()<<"x"<<coldCancel->height()
                <<" result="<<(retained?"PASS":"FAIL")<<std::endl;
        }
    }
    require(coldAll,"Cold first Keyboard lost fixed native button sizes");
    for(const QSize sz:{QSize(800,600),QSize(1024,768),QSize(1280,800),QSize(1920,1080)}) {
        QWidget outer; auto* layout=new QVBoxLayout(&outer); layout->setContentsMargins(0,0,0,0);
        // Reproduce ViewManager's real wrapper and registration-time margins.
        auto* manager=new QWidget; manager->setObjectName("viewManager");
        auto* ml=new QVBoxLayout(manager); ml->setContentsMargins(0,0,0,0);
        auto* stack=new QStackedWidget(manager); stack->setObjectName("viewManagerStack");
        stack->setContentsMargins(0,0,0,0); ml->addWidget(stack);
        stack->addWidget(keyboardPage());
        auto* partition=new QStackedWidget; partition->setContentsMargins(0,0,0,0);
        partition->addWidget(diskPage()); stack->addWidget(partition);
        QScrollArea* reviewScroll=nullptr; stack->addWidget(reviewPage(reviewScroll));
        // ViewManager::insertViewStep() overrides the already-built module layouts.
        for(int i=0;i<stack->count();++i)
            stack->widget(i)->layout()->setContentsMargins(10,10,10,10);
        auto* nav=new QWidget; auto* row=new QHBoxLayout;
        auto* back=new QPushButton("Back",nav); back->setObjectName("view-button-back"); row->addWidget(back);
        auto* next=new QPushButton("Continue",nav); next->setObjectName("view-button-next"); row->addWidget(next);
        auto* cancel=new QPushButton("Cancel",nav); cancel->setObjectName("view-button-cancel"); row->addWidget(cancel);
        coreVaultInstallNavigationSlots(nav,row); nav->setLayout(row);
        auto* shell=new CoreVaultWizardSurface(&outer,installerHeader(QString::fromLocal8Bit(argv[2])),manager,nav);
        layout->addWidget(shell); outer.resize(sz); outer.show(); app.processEvents();
        QRect firstTitle,firstNext,firstCancel,firstPage,firstNav;
        for(int step=0;step<3;++step) {
            stack->setCurrentIndex(step); back->setVisible(step!=0);
            next->show(); cancel->show();
            next->setText(step==2 ? "Erase drive and install" : "Continue");
            coreVaultSizeNavigationSlots(nav,step); shell->setStep(step);
            app.processEvents(); app.processEvents(); shell->arrange(); app.processEvents();
            auto* title=stack->currentWidget()->findChild<QLabel*>(
                step==2 ? "summaryTitle" : "coreOfflinePageTitle");
            require(title!=nullptr,"Page heading missing");
            const QRect tr=relativeRect(title,shell),nr=relativeRect(next,shell),cr=relativeRect(cancel,shell);
            if(step==0) {
                firstTitle=tr; firstNext=nr; firstCancel=cr;
                firstPage=manager->geometry(); firstNav=nav->geometry();
            } else {
                if(tr!=firstTitle)
                    std::cout<<"Registered heading mismatch step="<<step
                        <<" first="<<firstTitle.x()<<","<<firstTitle.y()<<","<<firstTitle.width()<<","<<firstTitle.height()
                        <<" actual="<<tr.x()<<","<<tr.y()<<","<<tr.width()<<","<<tr.height()<<std::endl;
                require(tr==firstTitle,"Page heading coordinates changed");
                require(nr==firstNext,"Primary button coordinates changed");
                require(cr==firstCancel,"Cancel button coordinates changed");
                require(manager->geometry()==firstPage && nav->geometry()==firstNav,"Page/navigation region changed");
            }
            require(nav->geometry().top()>manager->geometry().bottom(),"Buttons overlap page");
            require(nav->geometry().bottom()<shell->footer->geometry().top(),"Buttons overlap footer");
        }
        require(shell->header->height()>=shell->header->minimumSizeHint().height(),"Shared product header clipped");
        const int minimum=reviewScroll->widget()->minimumSizeHint().height();
        const int available=reviewScroll->viewport()->height();
        const int overflow=reviewScroll->verticalScrollBar()->maximum();
        std::cout<<"Review "<<sz.width()<<"x"<<sz.height()<<" minimum="<<minimum
            <<" viewport="<<available<<" scrollMaximum="<<overflow<<std::endl;
        if (minimum>available || overflow>0) {
            std::cout<<"Review diagnostics compact="<<shell->property("coreVaultCompact").toBool()
                <<" headerMinimum="<<shell->header->minimumSizeHint().height()
                <<" headerHeight="<<shell->header->height()
                <<" wrappedContent="<<reviewScroll->widget()->heightForWidth(reviewScroll->viewport()->width())
                <<std::endl;
            for(auto* label:stack->currentWidget()->findChildren<QLabel*>())
                std::cout<<"label "<<label->objectName().toStdString()
                    <<" fontPx="<<label->font().pixelSize()<<" size="<<label->width()<<"x"<<label->height()
                    <<" minimum="<<label->minimumSizeHint().height()
                    <<" hint="<<label->sizeHint().height()<<std::endl;
        }
        require(minimum<=available,"Complete Review content does not fit");
        require(overflow==0,"Review has unnecessary vertical overflow");
        std::cout<<"PASS styled native Qt title/navigation/Review "<<sz.width()<<"x"<<sz.height()<<std::endl;
        outer.hide();
        QWidget progressOuter; auto* pl=new QVBoxLayout(&progressOuter); pl->setContentsMargins(0,0,0,0);
        auto* progressPage=new CoreVaultExecutionSurface;
        auto* above=new QWidget(progressPage); auto* al=new QVBoxLayout(above); al->setContentsMargins(0,0,0,0);
        al->addWidget(new QLabel("Installing Bitcoin Core Vault"));
        al->addWidget(new QLabel("Please keep the computer powered on."));
        progressPage->above=above; progressPage->progress=new QProgressBar(progressPage);
        progressPage->progress->setMaximum(10000);
        auto* progressShell=new CoreVaultWizardSurface(&progressOuter,new QWidget,progressPage,new QWidget);
        pl->addWidget(progressShell); progressOuter.resize(sz); progressOuter.show(); app.processEvents();
        progressShell->setStep(3); app.processEvents(); progressPage->arrange();
        require(!progressShell->nav->isVisible(),"Navigation shown during execution");
        auto center=progressPage->progress->mapTo(&progressOuter,progressPage->progress->rect().center());
        require(qAbs(center.x()-progressOuter.rect().center().x())<=2,"Progress not centered horizontally");
        require(qAbs(center.y()-progressOuter.rect().center().y())<=2,"Progress not centered vertically");
        require(above->y()>=0,"Progress heading clipped");
        progressPage->progress->setValue(4200);
        require(progressPage->progress->value()==4200,"Progress value changed");
        std::cout<<"PASS retained native Qt execution geometry "<<sz.width()<<"x"<<sz.height()<<std::endl;
    }
    std::cout<<"VAULT INSTALLER V4 STYLED QT GEOMETRY TEST PASSED"<<std::endl;
}
'''
    with tempfile.TemporaryDirectory(prefix='vault-visual-test-') as td:
        p=Path(td);(p/'test.cpp').write_text(code);(p/'stylesheet.qss').write_text(style)
        flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs',qt],text=True))
        subprocess.run(['g++','-std=c++17','-fPIC',str(p/'test.cpp'),'-o',str(p/'test'),*flags],check=True)
        subprocess.run([str(p/'test'),str(p/'stylesheet.qss'),str(branding)],check=True,timeout=35,
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_SCALE_FACTOR='1',QT_AUTO_SCREEN_SCALE_FACTOR='0'))

if __name__=='__main__':
    import sys
    if sys.argv[1:]==['--self-test']: self_test()
    else: raise SystemExit('Use --self-test; patch_tree is called by the reviewed Calamares patcher.')
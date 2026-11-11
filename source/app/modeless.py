"""Independent navigation windows owned for their full process lifetime."""
from PySide6.QtCore import Qt

def root_of(owner):
    return getattr(owner,'navigation_owner',owner)

def open_window(owner,key,factory):
    root=root_of(owner)
    if not hasattr(root,'_modeless_windows'):root._modeless_windows={}
    current=root._modeless_windows.get(key)
    if current is not None:
        if current.isMinimized():current.showNormal()
        current.show();current.raise_();current.activateWindow()
        return current
    dialog=factory()
    dialog.setParent(None,Qt.Window)
    dialog.setWindowFlag(Qt.WindowMinimizeButtonHint,True)
    dialog.setWindowModality(Qt.NonModal);dialog.setModal(False)
    dialog.navigation_owner=root
    root._modeless_windows[key]=dialog
    def finished(_):
        if root._modeless_windows.get(key) is dialog:root._modeless_windows.pop(key,None)
        if key=='settings' and getattr(root,'settings_dialog',None) is dialog:root.settings_dialog=None
        dialog.deleteLater()
    dialog.finished.connect(finished)
    dialog.show();dialog.raise_();dialog.activateWindow()
    return dialog

def back_to_group(dialog):
    root=root_of(dialog)
    if getattr(dialog,'busy',False):dialog.showMinimized()
    else:dialog.reject()
    if hasattr(root,'backup_restore'):root.backup_restore()

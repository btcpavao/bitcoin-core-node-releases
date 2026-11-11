#!/usr/bin/python3
"""Adapt native LightDM GTK presentation, retaining upstream PAM handling."""
from pathlib import Path
import argparse
import subprocess
import xml.etree.ElementTree as ET

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Unexpected greeter source: ' + old[:80])
    return text.replace(old, new, 1)

def patch(source):
    path = source / 'src/lightdm-gtk-greeter.c'
    text = path.read_text()
    text = once(text,
        'start_authentication (const gchar *username)\n{\n',
        'start_authentication (const gchar *username)\n{\n'
        '    /* Node has one desktop account; no manual or guest selection. */\n'
        '    username = "node";\n')
    text = once(text, '    session = get_session ();\n',
        '    /* Use the root-owned Node desktop session. */\n'
        '    session = g_strdup ("core-node");\n')
    old = '''    if (lightdm_greeter_get_hide_users_hint (greeter))
    {
        set_user_image (NULL);
        start_authentication ("*other");
    }
    else
    {
        load_user_list ();
        gtk_widget_hide (GTK_WIDGET (cancel_button));
        gtk_widget_show (GTK_WIDGET (user_combo));
    }
'''
    new = '''    /* Fixed-account presentation; authentication still belongs to LightDM. */
    gtk_widget_set_no_show_all (GTK_WIDGET (user_combo), TRUE);
    gtk_widget_set_no_show_all (GTK_WIDGET (username_entry), TRUE);
    gtk_widget_set_no_show_all (GTK_WIDGET (cancel_button), TRUE);
    gtk_widget_set_no_show_all (panel_window, TRUE);
    gtk_widget_hide (GTK_WIDGET (user_combo));
    gtk_widget_hide (GTK_WIDGET (username_entry));
    gtk_widget_hide (GTK_WIDGET (cancel_button));
    gtk_widget_hide (panel_window);
    set_displayed_user (greeter, "node");
    /* Always use the shipped Bitcoin logo, not a user-editable avatar. */
    set_user_image (NULL);
    atk_object_set_name (gtk_widget_get_accessible (GTK_WIDGET (password_entry)),
                         "Login password");
'''
    text = once(text, old, new)
    anchor = '    /* Background */\n    greeter_background ='
    text = once(text, anchor, '''    /* Root-owned presentation only; no script or credential handling. */
    css_provider = gtk_css_provider_new ();
    gtk_css_provider_load_from_path (css_provider,
        "/usr/share/bitcoin-core-node/greeter.css", NULL);
    gtk_style_context_add_provider_for_screen (gdk_screen_get_default (),
        GTK_STYLE_PROVIDER (css_provider), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION + 1);
    g_object_unref (css_provider);

''' + anchor)
    path.write_text(text)

    path = source / 'src/lightdm-gtk-greeter.glade'
    tree = ET.parse(path)
    root = tree.getroot()
    def obj(name):
        matches = root.findall(".//object[@id='" + name + "']")
        if len(matches) != 1: raise RuntimeError('Unexpected greeter UI: ' + name)
        return matches[0]
    def prop(element, name, value):
        current = element.find("./property[@name='" + name + "']")
        if current is None: current = ET.SubElement(element, 'property', {'name': name})
        current.text = str(value)
        current.attrib.pop('translatable', None)
    def grid_position(child, row):
        packing = child.find('packing')
        if packing is None: packing = ET.SubElement(child, 'packing')
        for p in list(packing): packing.remove(p)
        prop(packing, 'left_attach', 0)
        prop(packing, 'top_attach', row)
    grid = obj('grid1')
    for name, value in [('row_spacing',16),('column_spacing',0),
                        ('margin_top',24),('margin_bottom',24)]:
        prop(grid, name, value)
    children = {child.find('object').get('id'): child for child in grid.findall('child')}
    for name, row in [('user_image_border',0),('password_entry',2),
                      ('user_combobox',4),('username_entry',5)]:
        grid_position(children[name], row)
    for name in ('user_combobox', 'username_entry'):
        prop(obj(name), 'visible', 'False')
        prop(obj(name), 'no_show_all', 'True')
        prop(obj(name), 'can_focus', 'False')
    for name, value in [('width_request',360),('margin_bottom',0),
                        ('placeholder_text','Password'),('hexpand','False')]:
        prop(obj('password_entry'), name, value)
    for ident, row, label in [('node_title',1,'Bitcoin Core Node'),
                              ('node_login_hint',3,'Press Enter to log in')]:
        child = ET.SubElement(grid, 'child')
        label_obj = ET.SubElement(child, 'object', {'class':'GtkLabel','id':ident})
        for name, value in [('name',ident),('visible','True'),
                            ('can_focus','False'),('label',label)]:
            prop(label_obj, name, value)
        grid_position(child, row)
    prop(obj('buttonbox_frame'), 'visible', 'False')
    prop(obj('buttonbox_frame'), 'no_show_all', 'True')
    prop(obj('message_label'), 'wrap', 'True')
    prop(obj('message_label'), 'max_width_chars', 40)
    ET.indent(tree, space='  ')
    tree.write(path, encoding='UTF-8', xml_declaration=True)
    # Release tarballs ship a pre-generated header; Debian disables maintainer mode.
    # Rebuild the embedded UI as well as its editable Glade source.
    with (source / 'src/lightdm-gtk-greeter-ui.h').open('wb') as header:
        subprocess.run(['xdt-csource', '--static', '--strip-comments', '--strip-content',
                        '--name=lightdm_gtk_greeter_ui', str(path)],
                       stdout=header, check=True)
    print('NODE LIGHTDM GTK GREETER PATCH APPLIED')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    patch(parser.parse_args().source.resolve())

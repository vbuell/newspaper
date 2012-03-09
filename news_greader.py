#!/usr/bin/env python
# -*- coding: utf-8 -*-
import Queue

import os
import datetime
import logging
import urllib2
import sys
from optparse import OptionParser
from datetime import date

import pygtk
import thread
import time

pygtk.require('2.0')
import gtk
import gconf
import gobject
import webkit
import pango
import webbrowser

from googlereaderapi import GoogleReader

VERSION = "0.93"


class Preferences:
    """
    Application preferences.
    """
    ROOT_DIR = '/apps/news'

    KEY_WINDOW_WIDTH = ROOT_DIR + '/ui_width'
    KEY_WINDOW_HEIGHT = ROOT_DIR + '/ui_height'
    KEY_GREADER_LOGIN = ROOT_DIR + '/greader_login'
    KEY_GREADER_PASS = ROOT_DIR + '/greader_pass'
    KEY_SEARCH_HISTORY = ROOT_DIR + '/search_history'

    windowWidth = 700
    windowHeight = 800
    windowX = 200
    windowY = 200
    greader_login = None
    greader_pass = None
    reverse = False
    keywords = None
    use_emailed_as_advanced_read = True
    page_size = 20
    search_history = []

    @staticmethod
    def load():
        # GConf stuff
        gconf_client = gconf.client_get_default()
        Preferences.gconf_client = gconf_client
        gconf_client.add_dir(Preferences.ROOT_DIR, gconf.CLIENT_PRELOAD_NONE)

        try:
            gconf_value = int(gconf_client.get_string(Preferences.KEY_WINDOW_WIDTH))
            if gconf_value:
                Preferences.windowWidth = gconf_value
            gconf_value = int(gconf_client.get_string(Preferences.KEY_WINDOW_HEIGHT))
            if gconf_value:
                Preferences.windowHeight = gconf_value
            gconf_value = gconf_client.get_string(Preferences.KEY_GREADER_LOGIN)
            if gconf_value:
                Preferences.greader_login = gconf_value
            gconf_value = gconf_client.get_string(Preferences.KEY_GREADER_PASS)
            if gconf_value:
                Preferences.greader_pass = gconf_value
            gconf_value = gconf_client.get_string(Preferences.KEY_SEARCH_HISTORY)
            if gconf_value:
                Preferences.search_history = gconf_value.split(";")

            logging.debug("Loaded preferences from gconf: " + str(Preferences.__dict__))
        except Exception, e:
            logging.exception(e)

    @staticmethod
    def save():
        Preferences.gconf_client.set_string(Preferences.KEY_WINDOW_WIDTH, str(Preferences.windowWidth))
        Preferences.gconf_client.set_string(Preferences.KEY_WINDOW_HEIGHT, str(Preferences.windowHeight))
        Preferences.gconf_client.set_string(Preferences.KEY_GREADER_LOGIN, str(Preferences.greader_login))
        Preferences.gconf_client.set_string(Preferences.KEY_GREADER_PASS, str(Preferences.greader_pass))
        Preferences.gconf_client.set_string(Preferences.KEY_SEARCH_HISTORY, ";".join(Preferences.search_history))

        logging.debug("Preferences saved.")

class Query:

    def next(self):
        pass

    def has_next(self):
        pass

class TopicQuery(Query):

    def __init__(self, google_reader, topic, from_past_to_now=False):
        self.topic = topic
        self.google_reader = google_reader
        self._has_next = False
        self.continuation = None
        self.from_past_to_now = from_past_to_now

    def next(self):
        if self.topic == "default":
            entries = self.google_reader.get_reading_list(
                from_past_to_now=self.from_past_to_now, continuation=self.continuation)
        else:
            entries = self.google_reader.get_entries(
                self.topic, from_past_to_now=self.from_past_to_now, continuation=self.continuation)

        if 'continuation' in entries:
            self._has_next = True
            self.continuation = entries['continuation']
        else:
            self._has_next = False
            self.continuation = None
        return entries

    def has_next(self):
        return self._has_next


class SearchQuery(Query):

    def __init__(self, google_reader, keywords, paging_size=20):
        self.keywords = keywords
        self.google_reader = google_reader
        self.entries_ids = self.google_reader.search(keywords, limit=2000)
        self.page = 0
        self.page_size = paging_size
        self.entries = None
        logging.info("Search returned " + str(len(self.entries_ids)) + " items.")

    def is_read(self, categories):
        for category in categories:
            if category.endswith('state/com.google/read'):
                return True
        return False

    def is_emailed(self, categories):
        for category in categories:
            if category.endswith('state/com.google/tracking-emailed'):
                return True
        return False

    def next(self):
        start = self.page * self.page_size
        end = (self.page + 1) * self.page_size

        entries = self.google_reader.get_items_by_ids(self.entries_ids[start:end])

        # Filter out read items
        if Preferences.use_emailed_as_advanced_read:
            items = [row for row in entries['items'] if not self.is_emailed(row['categories'])]
        else:
            items = [row for row in entries['items'] if not self.is_read(row['categories'])]
#        items = [row for row in entries['items'] if not self.is_read(row['categories'])]
        entries['items'] = items

        self.page += 1

        self.entries = entries

        logging.info("After filtering lasted " + str(len(entries['items'])) + " items.")

        return entries

    def has_next(self):
        logging.info("" + str(len(self.entries_ids)) + " > " + str(self.page * self.page_size))
        return len(self.entries_ids) > self.page * self.page_size

class News:

    def __init__(self):
        self.message_queue = Queue.Queue()
        self.quit = False

        Preferences.load()

        self.create_main_window()

        if not Preferences.greader_login or not Preferences.greader_pass:
            self.show_login(False)
        else:
            self.init_greader()

    def init_greader(self):
        try:
            logging.debug("Logging in as: " + str(Preferences.greader_login))
            self.google_reader = GoogleReader(Preferences.greader_login, Preferences.greader_pass)
            self.populate_feeds()
            if Preferences.keywords:
                print "Keywords", Preferences.keywords
                self.title_changed(None, None, "search#" + Preferences.keywords)
            else:
                self.title_changed(None, None, "tag#default")
        except urllib2.HTTPError:
            logging.exception("Forbidden")
            self.show_login(True)

    def delete_event(self, event, data=None):
        """Closes the app through window manager signal"""
        Preferences.save()
        gtk.main_quit()
        return False

    def title_changed(self, widget, frame, title):
        if title is None or "#" not in title:
            return
        self.message_queue.put(title)

    def run(self):
        while not self.quit:
            msg = self.message_queue.get()
            print "Got message:", msg
            self.command_process(msg)

    def command_process(self, title):
        logging.debug("COMMAND: " + str(title))
        command = title[:title.find("#")]
        rest = title[title.find("#")+1:]
        logging.debug("Command form UI: " + command + " # " + rest)
        if title.startswith("markasread#"):
#            print id
            try:
                self.google_reader.mark_as_read(rest, True)
                if Preferences.use_emailed_as_advanced_read:
                    self.google_reader.mark_as_emailed(rest, True)
            except:
                logging.exception("Can't mark as read")
                self.web_send('unslide("'+rest+'")')
        elif title.startswith("showbrowser#"):
            webbrowser.open_new_tab(rest)#, new = 0, autoraise = False)
        elif title.startswith("tag#"):
            if '#' in rest:
                chunks = rest.split('#')
                html_feed_page = self.return_entries_of_feed(chunks[0], continuation=chunks[1], from_past_to_now=Preferences.reverse)
            else:
                html_feed_page = self.return_entries_of_feed(rest, from_past_to_now=Preferences.reverse)
            self.render_html(html_feed_page)
        elif title.startswith("search#"):
            if rest not in Preferences.search_history:
                Preferences.search_history.append(rest)
            self.query = SearchQuery(self.google_reader, rest, paging_size=Preferences.page_size)
            if self.query.entries_ids:
                entries = self.query.next()
                while self.query.has_next() and not entries['items']:
                    entries = self.query.next()
                html_feed_page = self.render_as_html(entries, has_next=self.query.has_next())
                self.render_html(html_feed_page)
            else:
                asynchronous_gtk_message(self.search_unread)(None, True)
        elif title.startswith("login#"):
            Preferences.greader_login = rest[:rest.find("#")]
            Preferences.greader_pass = rest[rest.find("#")+1:]
            self.init_greader()
        elif title.startswith("logout#"):
            Preferences.greader_login = None
            Preferences.greader_pass = None
            self.show_login(False)
        elif title.startswith("next#"):
            entries = self.query.next()
            while self.query.has_next() and not entries['items']:
                entries = self.query.next()
            html_feed_page = self.render_as_html(entries, has_next=self.query.has_next())
            self.render_html(html_feed_page)

    def search_unread(self, action, error=None):
        f = open('./web/search.html', 'r')
        html = f.read()
        if error:
            html = html.replace("%error%", '<div id="login_error" class="hidden"><strong>Your query returned no entries.</strong><br /></div>')
        else:
            html = html.replace("%error%", '')

        html = html.replace("%history%", "".join(['<p><a class="search" style="font-weight: bold; " href="'+history+'">' + history + '</a>' for history in Preferences.search_history]))
        self.webview.load_string(html, "text/html", "utf-8", "valid_link")

    def render_html(self, html):
#        f = open("./out_debug.html", "w")
#        f.write(html)
#        f.close()
        # Fix for freezes
        html = html.replace("<iframe", "<ishame")
        asynchronous_gtk_message(self.webview.load_string)(html, "text/html", "utf-8", "")

    def web_send(self, msg):
        if msg:
            print '<<<', msg
            asynchronous_gtk_message(self.webview.execute_script)(msg)

    def show_about(self, action):
        """Shows the about message dialog"""
        about = gtk.AboutDialog()
        about.set_transient_for(self.window)
        about.set_program_name("News!")
        about.set_version(VERSION)
        about.set_comments("News! :: Minimalistic Google Reader frontend")
        about.set_copyright("(c) 2011 Volodymyr Buell")
        about.set_website("http://code.google.com/p/newspaper/")
        about.run()
        about.destroy()

    def create_ui(self, window):
        """Creates the menubar"""
        ui_string = """<ui>
               <menubar name='Menubar'>
                <menu action='HelpMenu'>
                 <menuitem action='About'/>
                </menu>
                <menu action='Action'>
                 <menuitem action='Mark as read all'/>
                 <menuitem action='Search unread articles'/>
                </menu>
               </menubar>
              </ui>"""

        ag = gtk.ActionGroup('WindowActions')
        actions = [
                ('HelpMenu', None, '_Help'),
                ('About', gtk.STOCK_ABOUT, '_About', None, 'About', self.show_about),
                ('Action', None, '_Action'),
                ('Mark as read all', None, '_Mark as read all', '<Control><Shift>a', 'About', self.mark_as_read_all),
                ('Search unread articles', None, '_Search unread articles', '<Control>s', 'Search unread articles', self.search_unread),
                ]
        ag.add_actions(actions)
        self.ui = gtk.UIManager()
        self.ui.insert_action_group(ag, 0)
        self.ui.add_ui_from_string(ui_string)
        self.window.add_accel_group(self.ui.get_accel_group())

    def create_main_window(self):
        """Creates the main window with all it's widgets"""
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.set_title("News!")
        self.window.connect("delete_event", self.delete_event)
        self.window.set_border_width(0)
        self.window.move(Preferences.windowX, Preferences.windowY)
        self.window.resize(Preferences.windowWidth, Preferences.windowHeight)

        self.vbox = gtk.VBox(False, 0)
        self.create_ui(self.window)
        self.vbox.pack_start(self.ui.get_widget('/Menubar'), False, True, 0)
        self.hpaned = gtk.HPaned()

        self.scrolled_window3 = gtk.ScrolledWindow()
        self.scrolled_window3.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.webview = webkit.WebView()
        self.webview.set_full_content_zoom(True)
        self.webview.connect_after("populate-popup", self.create_webview_popup)
        # Open in new browser handler (this intercepts all requests)
        self.webview.connect("hovering-over-link", self.hover_link)
        self.webview.connect('title-changed', self.title_changed)

        self.scrolled_window3.add(self.webview)

        self.hpaned.add2(self.scrolled_window3)
        self.vbox.pack_start(self.hpaned, True, True, 0)

        self.hbox2 = gtk.HBox(homogeneous=False, spacing=0)
        self.statusbar = gtk.Label("")
        self.statusbar.set_justify(gtk.JUSTIFY_LEFT)
        self.statusbar.set_ellipsize(pango.ELLIPSIZE_END)
        self.statusbar.set_alignment(xalign=0.01, yalign=0)
        self.hbox2.pack_start(self.statusbar, expand=True, fill=True, padding=0)
        self.vbox.pack_start(self.hbox2, False, False, 0)

        self.window.add(self.vbox)

        self.window.show_all()

    def create_webview_popup(self, view, menu):
        """Creates the webview (browser item) popup menu."""
        zoom_in = gtk.ImageMenuItem(gtk.STOCK_ZOOM_IN)
        zoom_in.connect('activate', self.zoom_in_cb, view)
        menu.append(zoom_in)
        zoom_out = gtk.ImageMenuItem(gtk.STOCK_ZOOM_OUT)
        zoom_out.connect('activate', self.zoom_out_cb, view)
        menu.append(zoom_out)
        zoom_hundred = gtk.ImageMenuItem(gtk.STOCK_ZOOM_100)
        zoom_hundred.connect('activate', self.zoom_hundred_cb, view)
        menu.append(zoom_hundred)
        menu.show_all()
        return False

    def zoom_in_cb(self, menu_item, web_view):
        """Zoom into the page"""
        web_view.zoom_in()

    def zoom_out_cb(self, menu_item, web_view):
        """Zoom out of the page"""
        web_view.zoom_out()

    def zoom_hundred_cb(self, menu_item, web_view):
        """Zoom 100%"""
        if not (web_view.get_zoom_level() == 1.0):
            web_view.set_zoom_level(1.0)

    def hover_link(self, title, uri, data=None):
        """Shows hovered link in Statusbar."""
        if data is not None:
            self.statusbar.set_text(data)
        else:
            self.statusbar.set_text("")

    def populate_feeds(self):
        counts = {}
        num, obj = self.google_reader.get_unread_count()
        for cntobj in obj['unreadcounts']:
            counts[cntobj['id']] = cntobj['count']

        subscriptions = self.google_reader.get_subscriptions()
        self.subscriptions = subscriptions

        # Get folders and create a map
        DEFAULT_LABEL = 'Others'
        categories = {}
        categories_id = {}
        for subscription in subscriptions['subscriptions']:
            cats = subscription['categories']
            if not cats:
                if DEFAULT_LABEL not in categories:
                    categories[DEFAULT_LABEL] = []
                categories[DEFAULT_LABEL].append(subscription)
            for cat in cats:
                categories_id[cat['label']] = cat['id']
                if cat['label'] not in categories:
                    categories[cat['label']] = []
                categories[cat['label']].append(subscription)

        self.html_tags = ""
        for category_name in categories:
            if category_name in categories_id:
                self.html_tags += '<p><span class="tag" style="font-weight: bold; " href="'+categories_id[category_name]+'">' + category_name + ':</span> '
            else:
                self.html_tags += '<p><b>' + category_name + ':</b> '

            for feed in categories[category_name]:
                if feed['id'] not in counts:
                    feed_label = feed['title']
                    font_style = 'normal'
                    # Do not add feed if empty
                else:
                    feed_label = feed['title'] + ' [' + str(counts[feed['id']]) + ']'
                    font_style = 'bold'
                    self.html_tags += '<span class="tag" href="'+feed['id']+'">' + feed_label + "&nbsp;</span>"

    def return_entries_of_feed(self, id_feed, continuation=None, from_past_to_now=False):
        """Obtains the entries of the selected feed"""
        if id_feed == "default":
            entries = self.google_reader.get_reading_list(from_past_to_now=from_past_to_now, continuation=continuation, number_of_items=Preferences.page_size)
        else:
            entries = self.google_reader.get_entries(id_feed, from_past_to_now=from_past_to_now, continuation=continuation, number_of_items=Preferences.page_size)

        return self.render_as_html(entries, id_feed, has_next=True)

    def render_as_html(self, entries, id_feed='NONE', has_next=False):
        f = open('./web/template.html', 'r')
        html = f.read()

        html_entries = ""
        for row in entries['items']:
            now = datetime.datetime.now().strftime("%Y-%m-%d")
            content = "Unexpected..."
            if 'content' in row:
                content = row['content']['content']
            elif 'summary' in row:
                content = row['summary']['content']
            else:
                content = row['title']

            entry_info = ''
            if 'origin' in row and 'title' in row['origin']:
                entry_info += row['origin']['title']

            if 'published' in row:
                entry_info += " : " + str(date.fromtimestamp(row['published']))

            if 'alternate' in row and row['alternate'] and 'href' in row['alternate'][0]:
                url = row['alternate'][0]['href']
                html_entries = html_entries + \
                               '<div class="article-section" name="'+str(row['id'])+'">' + \
                               '<div class="article-title" href="'+url+'">' + row['title'] + '<span>'+entry_info+'</span></div><div class="article">' + content + '</div><br></div>'
            else:
                html_entries = html_entries + \
                               '<div class="article-section" name="'+str(row['id'])+'">' + \
                               '<div class="article-title">' + row['title'] + '</div><div class="article">' + content + '</div><br></div>'

        if has_next:
            if 'continuation' in entries:
                continuation = entries['continuation']
                html_continuation = '<span class="tag" href="'+id_feed + '#'+continuation+'">Next...</span>'
            else:
                html_continuation = '<span class="tag">Next...</span>'
        else:
            html_continuation = ''

        html = html.replace("%entries%", html_entries)
        html = html.replace("%tags%", self.html_tags)
        html = html.replace("%feed_name%", id_feed)
        html = html.replace("%next%", html_continuation)

        return html

    def show_login(self, error):
        f = open('./web/login.html', 'r')
        html = f.read()
        if error:
            html = html.replace("%error%", '<div id="login_error" class="hidden"><strong>ERROR</strong>: Invalid email or username.<br /></div>')
        else:
            html = html.replace("%error%", '')
        self.webview.load_string(html, "text/html", "utf-8", "valid_link")

    def mark_as_read_all(self, action):
        urls = [row['id'] for row in self.query.entries['items']]
        self.google_reader.mark_as_read(urls, True)
        if Preferences.use_emailed_as_advanced_read:
            self.google_reader.mark_as_emailed(urls, True)
        if self.query.has_next():
            logging.debug("Mark as read all")
            self.title_changed(None, None, "next#")

    def read_filters(self, html):
        f = open("./adblock.filter", "r")
        filters = f.readlines()
        f.close()
        return filters


def asynchronous_gtk_message(fun):

    def worker((function, args, kwargs)):
        apply(function, args, kwargs)

    def fun2(*args, **kwargs):
        gobject.idle_add(worker, (fun, args, kwargs))

    return fun2

def synchronous_gtk_message(fun):

    class NoResult: pass

    def worker((R, function, args, kwargs)):
        R.result = apply(function, args, kwargs)

    def fun2(*args, **kwargs):
        class R: result = NoResult
        gobject.idle_add(callable=worker, user_data=(R, fun, args, kwargs))
        while R.result is NoResult: time.sleep(0.01)
        return R.result

    return fun2


if __name__ == "__main__":

    FORMAT = '%(asctime)s %(levelname)-8s %(message)s'
    logging.basicConfig(format=FORMAT, level=logging.DEBUG)
    logging.info("News! started...")

    parser = OptionParser()
    parser.add_option("-r", "--reverse", dest="reverse", action="store_true",
                      help="from past to now", default=False)
    parser.add_option("-n", "--page_size", dest="page_size",
                      help="page size", default=20)

    (options, args) = parser.parse_args(args=sys.argv)

    Preferences.reverse = options.reverse
    Preferences.page_size = int(options.page_size)
    if args[1:]:
        Preferences.keywords = ' '.join(args[1:])

    gtk.gdk.threads_init()

    news = News()
    thread.start_new_thread(news.run, ())

    gtk.main()

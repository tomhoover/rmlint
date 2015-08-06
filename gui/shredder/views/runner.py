#!/usr/bin/env python
# encoding: utf-8

# External:
from gi.repository import Gtk
from gi.repository import GLib

# Internal:
from shredder.util import View, IconButton
from shredder.chart import ChartStack
from shredder.tree import PathTreeView, PathTreeModel, Column
from shredder.runner import Runner


class ResultActionBar(Gtk.ActionBar):
    """Down right bar with the controls"""
    def __init__(self, view):
        Gtk.ActionBar.__init__(self)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.get_style_context().add_class("linked")
        self.pack_start(box)

        self.refresh_button = IconButton('view-refresh-symbolic')
        self.settings_button = IconButton('system-run-symbolic')

        self.refresh_button.connect(
            'clicked', lambda _: view.app_window.views['runner'].rerun()
        )
        self.settings_button.connect(
            'clicked', lambda _: view.app_window.views.switch('settings')
        )

        box.pack_start(self.refresh_button, False, False, 0)
        box.pack_start(self.settings_button, False, False, 0)

        self.script_btn = IconButton(
            'printer-printing-symbolic', 'Render script'
        )
        self.script_btn.get_style_context().add_class(
            Gtk.STYLE_CLASS_SUGGESTED_ACTION
        )
        self.script_btn.connect(
            'clicked', lambda _: view.app_window.views.switch('editor')
        )
        self.script_btn.set_sensitive(False)
        self.pack_end(self.script_btn)

    def finish(self):
        self.script_btn.set_sensitive(True)


class RunnerView(View):
    def __init__(self, app):
        View.__init__(self, app, 'Running…')

        # Public: The runner.
        self.runner = None

        # Disable scrolling for the main view:
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)

        # Public flag for checking if the view is still
        # in running mode (thus en/disabling certain features)
        self.is_running = False

        self.model = PathTreeModel([])
        self.treeview = PathTreeView()
        self.treeview.set_model(self.model)
        self.treeview.set_halign(Gtk.Align.FILL)
        self.treeview.get_selection().connect(
            'changed',
            self.on_selection_changed
        )

        # Scrolled window on the left
        scw = Gtk.ScrolledWindow()
        scw.set_vexpand(True)
        scw.set_valign(Gtk.Align.FILL)
        scw.add(self.treeview)

        self.chart_stack = ChartStack()
        self.actionbar = ResultActionBar(self)

        # Right part of the view
        stats_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        stats_box.pack_start(self.chart_stack, True, True, 0)
        stats_box.pack_start(self.actionbar, False, True, 0)
        stats_box.set_halign(Gtk.Align.FILL)
        stats_box.set_vexpand(True)
        stats_box.set_valign(Gtk.Align.FILL)

        # Separator container for separator|chart (could have used grid)
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        right_pane = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        right_pane.pack_start(separator, False, False, 0)
        right_pane.pack_start(stats_box, True, True, 0)

        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.attach(scw, 0, 0, 1, 1)
        grid.attach_next_to(right_pane, scw, Gtk.PositionType.RIGHT, 1, 1)

        self.add(grid)

        self.app_window.search_entry.connect(
            'search-changed', self.on_search_changed
        )

        # TODO: DEBUG
        # GLib.timeout_add(1000, lambda *_: self.trigger_run(['/usr/lib']))

    def trigger_run(self, paths):
        # Remember last paths for rerun()
        self.last_paths = paths

        # Make sure it looks busy:
        self.sub_title = 'Running…'

        # Fork off the rmlint process:
        self.runner = Runner(self.app.settings, paths)
        self.runner.connect('lint-added', self.on_add_elem)
        self.runner.connect('process-finished', self.on_process_finish)
        self.script = self.runner.run()

        # Make sure the previous run is not visible anymore:
        self.model = PathTreeModel([])
        self.treeview.set_model(self.model)

        # Indicate that we're in a fresh run:
        self.is_running = True
        self.app_window.show_progress(0)

    def rerun(self):
        self.trigger_run(self.last_paths)

    ###########################
    #     SIGNAL CALLBACKS    #
    ###########################

    def on_search_changed(self, entry):
        text = entry.get_text()

        if len(text) > 1:
            sub_model = self.model.filter_model(text)
            self.chart_stack.render(sub_model.trie.root)
            self.treeview.set_model(sub_model)

    def on_add_elem(self, runner):
        elem = runner.element
        self.model.add_path(elem['path'], Column.make_row(elem))

        # Decide how much progress to show (or just move a bit)
        tick = (elem.get('progress', 0) / 100.0) or None
        self.app_window.show_progress(tick)

    def on_process_finish(self, runner, error_msg):
        # Make sure we end up at 100% progress and show
        # the progress for a short time after (for the nice cozy feeling)
        self.app_window.show_progress(100)
        GLib.timeout_add(300, self.app_window.hide_progress)
        GLib.timeout_add(350, self.treeview.expand_all)

        self.sub_title = 'Finished scanning.'

        if error_msg is not None:
            self.app_window.show_infobar(
                error_msg, message_type=Gtk.MessageType.WARNING
            )

        GLib.timeout_add(1500, self.on_delayed_chart_render, -1)

    def on_delayed_chart_render(self, last_size):
        model = self.treeview.get_model()
        current_size = len(model)

        if current_size == last_size:
            # Come back later:
            return False

        if len(model) > 1:
            self.chart_stack.set_visible_child_name(ChartStack.CHART)
            self.chart_stack.render(model.trie.root)
            self.app_window.views.go_right.set_sensitive(True)
            self.actionbar.finish()
        else:
            self.chart_stack.set_visible_child_name(ChartStack.EMPTY)

        GLib.timeout_add(1500, self.on_delayed_chart_render, current_size)

        return False

    def on_view_enter(self):
        has_script = bool(self.runner)
        GLib.idle_add(
            lambda: self.app_window.views.go_right.set_sensitive(has_script)
        )

    def on_view_leave(self):
        self.app_window.views.go_right.set_sensitive(True)

    def on_selection_changed(self, selection):
        model, iter_ = selection.get_selected()
        if iter_ is not None:
            node = model.iter_to_node(iter_)
            self.chart_stack.render(node)

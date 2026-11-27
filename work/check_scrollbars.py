"""Verifica a aparência e a interação das barras ttk em janelas reais do Rota."""
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "outputs"))
import rota


def children(widget, cls):
    result = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            result.append(child)
        result.extend(children(child, cls))
    return result


def exercise(root, bar, view, prefix):
    root.update()
    assert bar.winfo_ismapped(), bar
    vertical = str(bar.cget("orient")) == "vertical"
    direction = "Vertical" if vertical else "Horizontal"
    length, width = bar.winfo_height(), bar.winfo_width()
    if not vertical:
        length, width = width, length
    def point(along, across):
        return (across, along) if vertical else (along, across)

    # Testa também a margem do indicador, que faz parte da área de arraste.
    names = [bar.identify(*point(i, 1)) for i in range(length)]
    thumb = f"Rota.{prefix}{direction}.Scrollbar.thumb"
    rail = f"Rota.{prefix}Scrollbar.trough"
    assert set(names) == {thumb, rail}, (bar, names[:10])
    start = names.index(thumb) + 3
    for event, along in (("<ButtonPress-1>", start), ("<B1-Motion>", start+length//3),
                         ("<ButtonRelease-1>", start+length//3)):
        x, y = point(along, 1)
        bar.event_generate(event, x=x, y=y)
        root.update()
    dragged = view()[0]
    assert dragged > 0, bar
    x, y = point(length-2, width//2)
    assert bar.identify(x, y) == rail
    bar.event_generate("<ButtonPress-1>", x=x, y=y)
    bar.event_generate("<ButtonRelease-1>", x=x, y=y)
    root.update()
    assert view()[0] > dragged, bar


def verify():
    with tempfile.TemporaryDirectory() as tmp:
        root = tk.Tk()
        store = rota.Workspace(Path(tmp))
        collection = store.state["roots"][0]
        request = collection["children"][0]
        for i in range(60):
            collection["children"].append(rota.make_node("request", f"Item {i:02} " + "extenso " * 10))
        for i in range(45):
            store.state["environments"].append(dict(id=rota.uid(), name=f"Ambiente {i:02}", variables=[]))
        request["params"] = [rota.row(f"campo_{i}", str(i)) for i in range(50)]
        app = rota.App(root, store)
        try:
            root.geometry("900x640")
            root.update()
            for bar in children(app.tree.master, ttk.Scrollbar):
                view = app.tree.yview if str(bar.cget("orient")) == "vertical" else app.tree.xview
                exercise(root, bar, view, "Nav.")
            canvas = children(app.editor, tk.Canvas)[0]
            bar = children(app.editor, ttk.Scrollbar)[0]
            exercise(root, bar, canvas.yview, "")
            canvas.yview_moveto(0)
            canvas.event_generate("<MouseWheel>", delta=-120)
            root.update()
            assert canvas.yview()[0] > 0

            app.remember(app.selected, rota.Reply(status=200, reason="OK", data=("\n".join(
                f"Linha {i:02} " + "texto " * 80 for i in range(80))).encode(),
                headers=[("Content-Type", "text/plain")]))
            app.set_body_mode("raw")
            root.update()
            text = children(app.response, tk.Text)[0]
            for bar in children(app.response, ttk.Scrollbar):
                view = text.yview if str(bar.cget("orient")) == "vertical" else text.xview
                exercise(root, bar, view, "")
            app.tree.xview_moveto(0)
            app.tree.yview_moveto(0)
            canvas.yview_moveto(0)
            text.xview_moveto(0)
            text.yview_moveto(0)
            root.update()
            root.geometry("1210x820")
            root.update()
            assert all(b.winfo_ismapped() for b in children(app.response, ttk.Scrollbar))

            data = "\n".join(",".join(f"{i}-{j}" for j in range(25)) for i in range(60))
            app.remember(app.selected, rota.Reply(status=200, data=data.encode(), headers=[("Content-Type","text/csv")]))
            app.set_body_mode("auto")
            table = children(app.response, ttk.Treeview)[0]
            for bar in children(app.response, ttk.Scrollbar):
                view = table.yview if str(bar.cget("orient")) == "vertical" else table.xview
                exercise(root, bar, view, "")
            app.select(collection["id"])
            root.update()
            listing = children(app.editor, ttk.Treeview)[0]
            bar = children(app.editor, ttk.Scrollbar)[0]
            exercise(root, bar, listing.yview, "")
            listing.delete(*listing.get_children())
            root.update()
            assert not bar.winfo_ismapped()

            dialog = rota.EnvironmentWindow(app, None)
            env_bar = children(dialog.list.master, ttk.Scrollbar)[0]
            exercise(root, env_bar, dialog.list.yview, "Panel.")
            dialog.list.delete(0, "end")
            root.update()
            assert not env_bar.winfo_ismapped()
            dialog.close()

            box = children(app.default_wrap, ttk.Combobox)[0]
            root.tk.call("ttk::combobox::Post", str(box))
            root.update()
            popup = root.tk.call("ttk::combobox::PopdownWindow", str(box))
            popup_bar = f"{popup}.f.sb"
            assert int(root.tk.call("winfo", "ismapped", popup_bar))
            assert str(root.tk.call(popup_bar, "identify", 2, 4)).startswith("Rota.")
            root.tk.call("ttk::combobox::Unpost", str(box))
        finally:
            app.close()
    print("OK rolagem vertical e horizontal, arraste pela margem, clique de página, ocultação e seletores.")


if __name__ == "__main__":
    verify()

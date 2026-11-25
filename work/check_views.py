"""Testes dos visualizadores. Executar da raiz com py -B work/check_views.py."""
import base64
import codecs
import gzip
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "outputs"))
import relay as r


def reply(mime, data, encoding="", truncated=False):
    headers = [("Content-Type", mime)] if mime else []
    if encoding:
        headers.append(("Content-Encoding", encoding))
    return r.Reply(status=200, data=data, headers=headers, truncated=truncated)


class ResponseViews(unittest.TestCase):
    def test_json_preserves_lexemes(self):
        raw = r'{"x":1e+999,"x":90071992547409930001,"items":[{},[],{"s":"a\\b\u0022"}]}'
        rep = reply("application/problem+json", raw.encode())
        pretty = r.body_view(rep)
        self.assertEqual(pretty.mode, "json")
        self.assertEqual(pretty.text.replace("\n","").replace(" ",""), raw)
        self.assertEqual(r.body_view(rep, "raw").text, raw)
        for value in ("true", "false", "null", '"string"', "23"):
            self.assertEqual(r.body_view(reply("application/json", value.encode())).text, value)

    def test_invalid_json_partial_and_empty(self):
        for body in (b'{"a":', b'{"a":NaN}'):
            view = r.body_view(reply("application/json", body))
            self.assertEqual(view.mode, "raw")
            self.assertEqual(view.text, body.decode())
            self.assertTrue(view.note)
        view = r.body_view(reply("application/json", b"[", truncated=True))
        self.assertIn("512 KiB", view.note)
        self.assertEqual(r.body_view(reply("", b"")).text, "Resposta sem corpo.")

    def test_csv_quotes_newlines_and_header(self):
        rep = reply("text/csv; header=present; charset=iso-8859-1",
                    'id,nome,nota\r\n1,"Ana, M.","Olá\r\nde novo"\r\n2,"A ""B""",\r\n'.encode("latin1"))
        view = r.body_view(rep)
        self.assertEqual(view.columns, ("id", "nome", "nota"))
        self.assertEqual(view.rows, [("1", "Ana, M.", "Olá\r\nde novo"), ("2", 'A "B"', "")])
        self.assertEqual(view.text, rep.data.decode("latin1"))
        rep = reply("text/csv; header=absent", b"1;A\n2;B\n")
        self.assertEqual(r.body_view(rep).rows, [("1","A"),("2","B")])
        self.assertEqual(r.body_view(reply("text/csv", b'"open,x')).mode, "raw")
        self.assertEqual(r.body_view(reply("text/tab-separated-values", b'1\t"x\ty"')).rows, [("1","x\ty")])

    def test_line_records_and_bounds(self):
        rep = reply("application/x-ndjson", b'{"a":1}\r\ntrue\nnull\n')
        self.assertEqual(r.body_view(rep).rows, [("1",'{"a":1}'),("2","true"),("3","null")])
        bad = r.body_view(reply("application/jsonl", b"null\n\n1\n"))
        self.assertIn("linha 2", bad.note)
        large = reply("text/csv", (b"x,"*70+b"\r\n") * (r.TABLE_ROWS+2))
        view = r.body_view(large)
        self.assertEqual(len(view.rows), r.TABLE_ROWS)
        self.assertEqual(len(view.columns), r.TABLE_COLUMNS)
        self.assertIn("limitada", view.note)
        self.assertEqual(view.text.encode(), large.data)

    def test_xml_tree_and_fallback(self):
        rep = reply("application/soap+xml", '<?xml version="1.0" encoding="ISO-8859-1"?><s:r xmlns:s="u">Olá<b n="2"/>fim</s:r>'.encode("latin1"))
        self.assertEqual(r.body_view(rep).rows, [("","s:r",'xmlns:s="u"'),("1","#texto","Olá"),("1","b",'n="2"'),("1","#texto","fim")])
        for data in (b"<one><two></one>", b"<!DOCTYPE r><r/>"):
            view = r.body_view(reply("text/xml",data))
            self.assertEqual(view.mode,"raw")
            self.assertEqual(view.text,data.decode())
            self.assertTrue(view.note)

    def test_text_and_detection(self):
        for mime in ("text/html", "text/markdown", "application/yaml", "application/javascript"):
            self.assertEqual(r.body_view(reply(mime,b"<tag>text</tag>")).mode, "text")
        self.assertEqual(r.body_view(reply("",b"\xff\xd8\xff")).mode, "hex")
        self.assertEqual(r.body_view(reply("", "Árvore".encode("utf-16"))).text, "Árvore")
        self.assertEqual(r.body_view(reply("application/json; charset=UTF-8", codecs.BOM_UTF8+b"{}")).mode,"json")
        self.assertTrue(r.body_view(reply("text/plain; charset=unknown",b"abc")).note)
        self.assertTrue(r.body_view(reply("text/plain",b"\xfe")).note)
        self.assertEqual(r.body_view(reply("text/plain",b"a,b\n1,2"), "csv").rows[0],("a","b"))

    def test_encoding_and_original_bytes(self):
        data = b'{"answer":1}'
        for encoding, compressed in (("gzip",gzip.compress(data)), ("deflate",zlib.compress(data))):
            rep = reply("application/json",compressed,encoding)
            self.assertEqual(r.body_view(rep,"raw").text, data.decode())
            self.assertEqual(base64.b64decode(r.body_view(rep,"base64").text), compressed)
            self.assertIn(compressed[:4].hex(" "), r.body_view(rep,"hex").text)
        for rep in (reply("text/plain",b"encoded","br"), reply("text/plain",b"bad","gzip"),
                    reply("text/plain",gzip.compress(b"hello")[:-4],"gzip")):
            view = r.body_view(rep)
            self.assertEqual(view.mode,"hex")
            self.assertTrue(view.note)
        view = r.body_view(reply("text/plain",gzip.compress(b"x"*(r.PREVIEW_LIMIT+2)),"gzip"))
        self.assertEqual(len(view.text),r.PREVIEW_LIMIT)
        self.assertIn("512 KiB",view.note)

    def test_binary_and_png_limits(self):
        view = r.body_view(reply("application/pdf",b"%PDF-1.7\x00\xff"))
        self.assertIn("25 50 44 46",view.text)
        self.assertIn("%PDF-1.7..",view.text)
        huge = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"+(20000).to_bytes(4,"big")*2
        self.assertEqual(r.body_view(reply("image/png",huge)).mode,"hex")
        self.assertIn("16 KiB", r.body_view(reply("application/octet-stream",bytes(r.HEX_LIMIT+1))).note)


if __name__ == "__main__":
    unittest.main(verbosity=2)

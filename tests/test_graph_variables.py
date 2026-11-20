"""Safe ephemeral graph variables and browser text capture."""
from __future__ import annotations

import asyncio
import unittest

from autumn_genlogin.graph import execute_graph, validate_graph


def graph(*nodes):
    all_nodes=[{"id":"start","type":"start"}]
    all_nodes.extend(nodes)
    all_nodes.append({"id":"end","type":"end"})
    edges=[{"from":a["id"],"to":b["id"],"branch":"next"} for a,b in zip(all_nodes,all_nodes[1:])]
    return {"format":"AutumnGenLogin/graph-1","nodes":all_nodes,"edges":edges}


def set_node(ident,name,value):
    return {"id":ident,"type":"set_variable","name":name,"value":value}


def action_node(ident,step):
    return {"id":ident,"type":"action","step":step}


def capture_node(ident,name,selector):
    return {"id":ident,"type":"capture_text","name":name,"selector":selector}


class VariableGraphTests(unittest.TestCase):
    def run_graph(self,definition,capture=None):
        calls=[]
        async def action(step):calls.append(step)
        async def exists(selector):return False
        result=asyncio.run(execute_graph(definition,action=action,exists=exists,capture=capture))
        return calls,result

    def test_set_variable_expands_fill_and_exposes_no_values_in_status(self):
        definition=graph(
            set_node("value","greeting","Autumn sample"),
            action_node("fill",{"action":"fill","selector":"#target","text":"{{greeting}}"}),
        )
        self.assertEqual(validate_graph(definition),definition)
        calls,result=self.run_graph(definition)
        self.assertEqual(calls,[{"action":"fill","selector":"#target","text":"Autumn sample"}])
        self.assertEqual(result,{"status":"succeeded","operations":3})
        self.assertNotIn("Autumn sample",str(result))

    def test_capture_text_passes_page_text_to_later_action(self):
        definition=graph(
            capture_node("read","headline","#heading"),
            action_node("write",{"action":"fill","selector":"#target","text":"{{headline}}"})
        )
        seen=[]
        async def capture(selector):
            seen.append(selector)
            return "private page text"
        calls,result=self.run_graph(definition,capture)
        self.assertEqual(seen,["#heading"])
        self.assertEqual(calls[-1]["text"],"private page text")
        self.assertNotIn("private page text",str(result))

    def test_page_capture_cannot_be_used_in_goto_url(self):
        definition=graph(
            capture_node("read","secret","#private"),
            action_node("navigate",{"action":"goto","url":"https://example.org/?q={{secret}}"})
        )
        calls=[]
        async def action(step):calls.append(step)
        async def exists(selector):return False
        async def capture(selector):return "SENSITIVE-DO-NOT-EXFIL"
        with self.assertRaisesRegex(ValueError,"Captured page text"):
            asyncio.run(execute_graph(definition,action=action,exists=exists,capture=capture))
        self.assertEqual(calls,[])

    def test_undefined_variable_and_unrecognized_template_fail_closed(self):
        for token in ("{{missing}}","{{ missing }}","{{variable.with.path}}"):
            with self.subTest(token=token):
                definition=graph(action_node("fill",{
                    "action":"fill","selector":"#target","text":token
                }))
                with self.assertRaises(ValueError):
                    self.run_graph(definition)

    def test_capture_requires_explicit_browser_callback(self):
        definition=graph(capture_node("read","data","#heading"))
        with self.assertRaisesRegex(RuntimeError,"not available"):
            self.run_graph(definition)

    def test_capture_clamps_to_4096_characters(self):
        definition=graph(
            capture_node("read","long","#heading"),
            action_node("use",{"action":"fill","selector":"#target","text":"{{long}}"})
        )
        async def capture(_):return "x"*5000
        calls,result=self.run_graph(definition,capture)
        self.assertEqual(len(calls[0]["text"]),4096)
        self.assertEqual(result["status"],"succeeded")

    def test_late_validation_rejects_illegal_expanded_navigation_url(self):
        definition=graph(
            set_node("set","bad","example.org\nSet-Cookie: injected"),
            action_node("nav",{"action":"goto","url":"https://{{bad}}/"})
        )
        with self.assertRaisesRegex(ValueError,"Invalid URL"):
            self.run_graph(definition)

    def test_invalid_variable_names_and_values_are_rejected(self):
        for name in ("", "not-ok", "space name", "é", "1starting", "a"*33):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_graph(graph(set_node("literal",name,"safe")))
        for value in ("{{undefined}}", "x"*4097, "\x00"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_graph(graph(set_node("literal","data",value)))

    def test_graph_enforces_variable_count(self):
        nodes=[set_node("var_"+str(i),"v"+str(i),"a") for i in range(33)]
        with self.assertRaisesRegex(ValueError,"32 distinct"):
            validate_graph(graph(*nodes))

    def test_dynamic_selector_and_non_captured_navigation_allowed(self):
        definition=graph(
            set_node("target","tag","h1"),
            set_node("origin","domain","example.org"),
            action_node("nav",{"action":"goto","url":"https://{{domain}}/"}),
            capture_node("capture","title","{{tag}}"),
            action_node("fill",{"action":"fill","selector":"input","text":"{{title}}"})
        )
        seen=[]
        async def capture(selector):
            seen.append(selector)
            return "demo"
        calls,result=self.run_graph(definition,capture)
        self.assertEqual(calls[0]["url"],"https://example.org/")
        self.assertEqual(seen,["h1"])
        self.assertEqual(calls[1]["text"],"demo")
        self.assertEqual(result["status"],"succeeded")


if __name__=="__main__":
    unittest.main()

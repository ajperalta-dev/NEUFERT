from pipeline import llm

def test_generated_facts_and_unknown_pages_are_discarded(monkeypatch):
    monkeypatch.setattr(llm,'call',lambda *args:{'evidence':[{'id':'a','quote':'width 1.2 m'},{'id':'a','quote':'minimum width 9 m'},{'id':'unknown','quote':'width 1.2 m'}]})
    assert llm.evidence('stairs',[{'id':'a','text':'Clear width 1.2 m','pagina_pdf':42}])==[{'id':'a','quote':'width 1.2 m','page':42}]

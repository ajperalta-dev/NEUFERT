"""Curated labels, never inferred measurements or normative recommendations."""
import re
import unicodedata

TERMS = {
 'typology': {
  'vivienda': ('housing residential dwelling house wohnung wohnhaus wohnen', 'Vivienda', 'Housing', 'Wohnen'),
  'oficina': ('office offices buro büro verwaltung', 'Oficina', 'Office', 'Büro'),
  'educacion': ('school classroom education university schule hochschule kindergarten', 'Educación', 'Education', 'Bildung'),
  'salud': ('hospital healthcare clinic krankenhaus pflege', 'Salud', 'Healthcare', 'Gesundheit'),
  'comercio': ('shop retail shopping store laden verkauf', 'Comercio', 'Retail', 'Handel'),
  'industria': ('factory industrial workshop industrie fabrik werkstatt', 'Industria', 'Industry', 'Industrie'),
  'deporte': ('sport sports swimming gymnasium schwimmen turnhalle', 'Deporte', 'Sports', 'Sport'),
  'cultura': ('museum theatre theater cinema library bibliothek kultur', 'Cultura', 'Culture', 'Kultur'),
  'hosteleria': ('hotel restaurant catering hostel gastronomie', 'Hostelería', 'Hospitality', 'Gastgewerbe'),
  'transporte': ('transport railway airport parking garage bahnhof verkehr', 'Transporte', 'Transport', 'Verkehr'),
  'agricultura': ('agriculture farm farming livestock landwirtschaft stall', 'Agricultura', 'Agriculture', 'Landwirtschaft')},
 'space': {
  'dormitorio': ('bedroom sleeping schlafzimmer', 'Dormitorio', 'Bedroom', 'Schlafzimmer'),
  'cocina': ('kitchen kitchens küche', 'Cocina', 'Kitchen', 'Küche'),
  'bano': ('bathroom toilet toilets wc bad badezimmer', 'Baño', 'Bathroom', 'Bad'),
  'aula': ('classroom classrooms klassenraum', 'Aula', 'Classroom', 'Klassenraum'),
  'garaje': ('garage garages parking parkplatz', 'Garaje', 'Garage', 'Garage'),
  'pasillo': ('corridor corridors hallway flur gang', 'Pasillo', 'Corridor', 'Flur'),
  'escalera': ('stairs staircase stair stairways treppe treppen', 'Escalera', 'Stairs', 'Treppe'),
  'comedor': ('dining cafeteria esszimmer', 'Comedor', 'Dining', 'Esszimmer'),
  'ascensor': ('lift lifts elevator aufzug', 'Ascensor', 'Lift', 'Aufzug')},
 'use': {
  'accesibilidad': ('accessibility accessible wheelchair wheelchairs rollstuhl rollstühle barrierefrei discapacidad ruedas', 'Accesibilidad', 'Accessibility', 'Barrierefreiheit'),
  'dormir': ('sleeping sleep schlafen', 'Dormir', 'Sleeping', 'Schlafen'),
  'circular': ('circulation access circulation erschliessung erschließung', 'Circular', 'Circulation', 'Erschließung'),
  'trabajar': ('working work arbeiten', 'Trabajar', 'Working', 'Arbeiten'),
  'cocinar': ('cooking kochen', 'Cocinar', 'Cooking', 'Kochen'),
  'aprender': ('teaching learning unterricht lernen', 'Aprender', 'Learning', 'Lernen')},
 'furniture': {
  'cama': ('bed beds bett betten', 'Cama', 'Bed', 'Bett'),
  'mesa': ('table tables desk tisch schreibtisch', 'Mesa', 'Table', 'Tisch'),
  'silla': ('chair chairs seating stuhl sitz', 'Silla', 'Chair', 'Stuhl'),
  'armario': ('cupboard wardrobe cabinet schrank', 'Armario', 'Cupboard', 'Schrank'),
  'lavabo': ('washbasin basin sink waschbecken', 'Lavabo', 'Washbasin', 'Waschbecken')}
}

def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.lower()) if not unicodedata.combining(c))

def match_terms(text):
    words = set(re.findall(r'\w+',normalize(text)))
    return [(kind,key) for kind,items in TERMS.items() for key,labels in items.items()
            if words.intersection(re.findall(r'\w+',normalize(' '.join(labels) + ' ' + key)))]

def expand_query(query):
    terms = re.findall(r'\w+', normalize(query))
    stop = set('cuanto cuanta necesita necesita un una el la los las de del para en por minimo minima ancho the a an of for how much what minimum is are der die das ein eine fur wie und'.split())
    result = [t for t in terms if t not in stop and len(t)>1]
    for kind,key in match_terms(query):
        result.extend(re.findall(r'\w+',normalize(' '.join(TERMS[kind][key]))))
    return list(dict.fromkeys(result))[:100]

def translated_title(title, language):
    # Translate exact vocabulary headings only; unknown titles remain null.
    result = {'de': None, 'es': None, 'en': None}
    result[language] = title
    for items in TERMS.values():
        for terms,es,en,de in items.values():
            if normalize(title) in [normalize(x) for x in (es,en,de)] or normalize(title) in terms.split():
                return {'de':de, 'es':es, 'en':en}
    return result

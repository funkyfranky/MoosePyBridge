# DCS Navigation Project

Status: Konzept- und Vorbereitungsphase  
Stand: 29. August 2026

## Zweck dieses Dokuments

Dieses Dokument sammelt den bisherigen Erkenntnisstand, Architekturideen,
Entscheidungen, Risiken und nächsten Schritte für ein neues Python-basiertes
Navigationsprojekt im Umfeld von DCS World und MOOSE.

Das Projekt ist noch nicht auf einen endgültigen Produktumfang festgelegt. Der
empfohlene Einstieg ist ein deterministischer Navigations- und
Flugplanungskern. Ein AI-Copilot und ein AI-ATC können später auf demselben Kern
aufbauen.

## Produktvision

Eine Python-basierte Navigations- und Flugplanungsplattform für DCS World, die
aktuelle Navigationsdaten mit dem tatsächlichen DCS-Missionszustand verbindet
und Piloten, Cockpitsystemen, MOOSE-gesteuerten KI-Flügen und später
sprachbasierten Assistenten strukturierte Navigationsdienste bereitstellt.

Ein erster vollständiger Anwendungsfall soll sein:

> Der Nutzer wählt Start, Ziel und Flugzeug. Das System erzeugt eine fliegbare
> Route mit Runway, Abflug, Enroute-Segment, Ankunft und Approach und begleitet
> den Piloten während des Fluges.

## Projektprinzipien

- Navigation, Routenberechnung und Validierung sind deterministische
  Kernfunktionen. Ein Sprachmodell darf sie bedienen und erklären, aber nicht
  durch unkontrollierte freie Entscheidungen ersetzen.
- Der interne Flugplan bleibt unabhängig von Navigraph, DCS, MOOSE und einem
  bestimmten Flugzeugmodul.
- Navigraph, DCS/MOOSE, DTC und Cockpitmodule werden über Adapter angebunden.
- DCS bleibt für den laufenden Simulationszustand maßgeblich.
- Navigraph-Daten dürfen ausschließlich für Flugsimulation und gemäß den
  Navigraph-Lizenzbedingungen verwendet werden.
- Automatische Aktionen benötigen typisierte Aufträge, Validierung und bei
  risikoreichen Aktionen eine explizite Bestätigung. Das Aktivierungsmodell von
  MoosePyBridge ist dafür ein geeignetes Vorbild.
- Geheimnisse wie Navigraph Client Secret, Access Token und Refresh Token
  dürfen weder in Git noch in Logs oder DTC-Dateien gelangen.

## Vorgesehene Ausbaustufen

### 1. Navigations- und Flugplanungskern

Eingaben können unter anderem sein:

- Start- und Zielflugplatz
- Flugzeugtyp und Navigationsausstattung
- IFR/VFR oder taktische Missionsart
- Startzeit
- DCS-Wetter und Wind
- gewünschte Reiseflughöhe oder Optimierungsziel
- zu meidende Lufträume und Bedrohungsgebiete

Mögliche Ergebnisse:

- Start- und Landebahn
- SID oder sinnvolle Abflugroute
- Enroute-Wegpunkte und Airways
- Reiseflughöhe
- STAR oder Anflugübergang
- Instrumentenanflug und Missed Approach
- optionale Holdings
- Kurse, Distanzen, Höhen, Geschwindigkeitsbeschränkungen und ETA
- strukturierte Wegpunktliste für verschiedene Ausgaben

Holdings werden nicht pauschal in jede Route eingebaut. Sie entstehen aus
einem Verfahren, einer ATC-Anweisung, einer Warteanforderung oder einer
dynamischen Verkehrssituation.

### 2. DTC- und Cockpitintegration

Der berechnete Flugplan soll für unterstützte DCS-Module in ein geeignetes
Data-Transfer-Cartridge-Format übersetzt werden. Dadurch kann die Cockpiteingabe
stark vereinfacht oder vollständig ersetzt werden.

Zusätzliche Ausgaben können sein:

- MOOSE-/DCS-Route für KI-Flugzeuge
- Kneeboard oder Mission Card
- F10-Marker
- maschinenlesbare JSON-Ausgabe
- schrittweise Eingabeanleitung für den Copiloten

### 3. AI-Copilot

Der Copilot kann schrittweise erweitert werden:

1. **Advisory:** Er erklärt Flugplan, Frequenzen, Kurse, Checklisten und
   Cockpiteingaben.
2. **Assisted:** Er bereitet typisierte Eingaben vor und wartet auf eine
   Bestätigung.
3. **Automatic:** Er bedient ausdrücklich unterstützte Cockpitsysteme über
   modulspezifische Adapter.

Mögliche Aufgaben:

- Flugplan erklären und Änderungen begründen
- Wegpunkt- und Funkdaten vorbereiten
- Checklisten begleiten
- Navigation und Cross-Track-Error überwachen
- nächste Aktionen, Höhen und Frequenzen ansagen
- Treibstoff, ETA und Ausweichoptionen überwachen
- Funktexte vorbereiten
- bei einer Umplanung eine neue DTC oder Eingabesequenz erzeugen

Eine generische Cockpitbedienung gibt es in DCS nicht. F-16C, F/A-18C, A-10C,
AH-64D und andere Module benötigen jeweils eigene Adapter, möglicherweise über
DCS-BIOS, Export-Lua oder modulspezifische Cockpitbefehle.

### 4. Flight Instructor

Der Flight Instructor ist eine eigene Rolle neben dem Copiloten. Der Copilot
hilft bei der Ausführung, während der Instructor beobachtet, bewertet, erklärt
und gezielt trainiert.

Vorgesehene Betriebsarten:

- **Briefing:** Route, Verfahren, Lernziele und erwartete Fehlerquellen erklären
- **Silent:** nur auf Nachfrage helfen
- **Training:** kontextbezogene Hinweise bei relevanten Abweichungen geben
- **Strict:** Verfahren und Toleranzen eng überwachen
- **Exam:** während des Fluges schweigen und anschließend bewerten
- **Debriefing:** Fehlerchronik, Bewertung und Übungsempfehlungen erzeugen

Mögliche Überwachungsbereiche:

- Soll- und Ist-Höhe, Geschwindigkeit und Kurs
- Cross-Track-Error, Steig-/Sinkrate und ETA
- Flugphase und korrekte Flugzeugkonfiguration
- Anflugprofil, Localizer, Glideslope und Angle of Attack
- Fahrwerk, Klappen, Airbrake, Treibstoff und Bingo
- Checklisten und Verfahrensschritte
- Sensor-, Radar-, Defensive- und Waffensystemzustände
- Voraussetzungen und simulierte Einsatzparameter eines Waffeneinsatzes

Die Erkennung einer Abweichung erfolgt deterministisch aus DCS-Telemetrie,
Flugplan, Flugphase und einem flugzeugspezifischen Trainingsprofil. Ein
Sprachmodell entscheidet nur über verständliche Erklärung, Dialog und den
geeigneten Zeitpunkt einer nichtkritischen Hilfestellung. Toleranzen,
Prioritäten, Hysterese und Wiederholungsunterdrückung verhindern unnötige oder
ständige Hinweise.

Als erstes Referenz- und Testflugzeug wird die **DCS: F/A-18C Hornet**
verwendet. Der erste Instructor-Prototyp soll IFR-Navigation, Flugphasen,
Höhen-/Geschwindigkeitsführung und einen stabilisierten Anflug überwachen.
Sensor- und Waffensystemkurse werden danach modular ergänzt.

### 5. ATIS und AI-ATC

Ein vollständiges AI-ATC ist ein langfristiges, eigenständiges Großprojekt. Es
soll auf dem Navigationskern aufbauen und in kleinen Stufen entstehen:

1. ATIS/AWOS
2. unverbindliche Verkehrsinformationen
3. Tower für einen Flugplatz
4. Approach Controller mit Sequenzierung, Vektoren und Holdings
5. regionales ATC mit Sektoren, Übergaben und Staffelung
6. militärische Ergänzungen wie Formation Flights, GCI, Marshal, Carrier und
   taktische Lufträume

Staffelung, Runway-Belegung, Konflikterkennung und Freigabestatus müssen
deterministisch berechnet werden. Ein Sprachmodell ist nur für Dialog,
Interpretation und natürliche Formulierungen zuständig.

## Navigraph-Erkenntnisse

### Zugriff

- Der Antrag auf Navigraph-Entwicklerzugang wurde am 29. August 2026 per E-Mail
  versendet.
- Angefragt werden sollen beziehungsweise wurden empfohlen:
  - Navigation Data API
  - DFD v2 im SQLite-Format
  - Device Authorization Flow with PKCE
  - lokale Python-Anwendung für DCS World
- Das persönliche Navigraph-Abonnement berechtigt das Benutzerkonto zu den
  abonnierten Daten, ersetzt aber nicht die Entwicklerfreigabe.
- Für die API werden anwendungsbezogene `Client ID` und `Client Secret`
  benötigt.
- Jeder Endnutzer authentifiziert sich mit seinem eigenen Navigraph-Konto.

### Navigation Data API

Die API ist keine Such-API für einzelne Wegpunkte. Sie liefert vollständige,
AIRAC-gebundene Datenpakete. Der relevante Einstiegspunkt ist:

```http
GET https://api.navigraph.com/v1/navdata/packages
Authorization: Bearer <access-token>
```

Die Paketbeschreibung enthält unter anderem:

- AIRAC Cycle und Revision
- Paketstatus `outdated`, `current` oder `future`
- Format
- Dateien
- SHA-256-Prüfsummen
- kurzlebige Download-URLs

Die Anwendung lädt das passende Paket herunter und führt Suche,
Graphaufbereitung und Routenberechnung lokal aus. Beim Start werden Cycle,
Revision und Hash geprüft und nur geänderte Pakete aktualisiert.

### Authentifizierung

Für eine lokale Desktop- beziehungsweise Simulatoranwendung ist der Device
Authorization Flow mit PKCE vorgesehen. Typische Scopes sind:

```text
openid offline_access fmsdata
```

Der Benutzer autorisiert die Anwendung über Browser, Code oder QR-Code. Das
Access Token ist ungefähr eine Stunde gültig. Das langlebigere Refresh Token
wird beim Refresh ersetzt und muss atomar sowie geschützt gespeichert werden.

### DFD v2

DFD v2 ist an ARINC 424 angelehnt und kann als SQLite oder Textdatensatz
geliefert werden. Relevante Datentypen sind:

- Airports, Runways und Gates
- VHF-Navaids, DME, ILS und GLS
- Enroute- und Terminal-NDBs
- Enroute- und Terminal-Waypoints
- Airways und Airway Restrictions
- Holdings
- SID, STAR und Instrument Approaches
- Airport- und Enroute-Kommunikation
- MSA und Grid MORA
- kontrollierte und beschränkte Lufträume
- FIR/UIR
- Procedure Path Points

Die Verfahrensdaten enthalten ARINC-artige Legs und Constraints. Der Planner
muss daraus fliegbare, zusammenhängende Segmente erzeugen.

Offizielle Entwicklungsmuster stehen bereits mit geografisch begrenzten,
älteren DFD-v1/v2-Beispieldaten zur Verfügung. Diese dürfen nur zur Entwicklung
und Evaluation und nicht zur Weiterverteilung verwendet werden.

### Charts API

Die Charts API liefert Airport-Charts als hochauflösende Tag-/Nacht-PNGs sowie
Enroute-Karten als Web-Mercator-Tiles. Airport-Charts können Metadaten,
Verfahrens- und Runway-Zuordnungen sowie Georeferenzierung enthalten.

Für dieses Projekt wird die Charts API zunächst nicht benötigt. Wichtige
Einschränkungen:

- Charts dürfen nicht offline gespeichert oder gecacht werden.
- Eine normale eigenständige Desktop-Charts-Anwendung wird grundsätzlich nicht
  genehmigt.
- Zulässig sind typischerweise virtuelle EFBs im Simulator. Eng an eine aktive
  Simulation gebundene lokale Zusatzanzeigen müssen von Navigraph geprüft
  werden.
- Aus FMS-Navigationsdaten dürfen keine kartenähnlichen Navigraph-Ersatzprodukte
  erzeugt werden.

Eine spätere Kartenansicht muss deshalb technisch und lizenzrechtlich klar von
einem Navigraph-Charts-Produkt abgegrenzt und gegebenenfalls vorab genehmigt
werden.

### SimBrief

SimBrief kann als optionaler Flugplanlieferant beziehungsweise Importquelle
dienen. Der letzte OFP eines Benutzers kann als XML oder JSON abgerufen werden.
Das aktive Erzeugen von Flugplänen über eine eigene Integration benötigt einen
separat beantragten SimBrief-API-Key.

SimBrief ist für zivile Flugplanung nützlich, ersetzt aber keinen eigenen
Planner für militärische DCS-Flugzeuge, taktische Routen oder
Bedrohungsvermeidung.

## DCS- und MOOSE-Erkenntnisse

DCS liefert beziehungsweise kontrolliert:

- laufenden Missionszustand
- Spieler- und KI-Positionen
- Wetter und Wind
- DCS-Flugplätze und tatsächlich implementierte Funkfeuer
- Terrain und Theaterkoordinaten
- missionsspezifische Beacons, Carrier und TACAN-Stationen
- Bedrohungen, Koalitionen und taktische Missionslage

MoosePyBridge überwacht jetzt den Spieler-Slot-Lebenszyklus über MOOSE
`PlayerEnterAircraft` und DCS `PlayerLeaveUnit`. Die normalisierten Events
`player.aircraft.entered` und `player.aircraft.left` enthalten Spieler, Unit,
Gruppe und – sofern vorhanden – die zugehörige `FLIGHTGROUP` als geerbte
`OPSGROUP`. Damit können Navigation, Copilot und Flight Instructor ihre Session
beim Einstieg starten und beim Verlassen zuverlässig beenden. Eintrittsdaten
werden kurzzeitig in Lua zwischengespeichert, weil das Leave-Event nicht in
allen DCS-Situationen noch sämtliche Spieler- und Wrapperdaten enthält. DCS kann
`PlayerLeaveUnit` innerhalb weniger Millisekunden doppelt auslösen. Die Bridge
unterdrückt deshalb gleiche Leave-Ereignisse pro Spieler beziehungsweise Unit
innerhalb einer Sekunde; ein erneuter Einstieg setzt dieses Fenster sofort
zurück.

Die Bridge verarbeitet `PlayerEnterAircraft` zusätzlich um 0,5 Sekunden
verzögert. So können Missionsskripte im selben Event zunächst die
`FLIGHTGROUP` erstellen; die Bridge löst die `OPSGROUP` erst danach auf.
Verlässt der Spieler den Slot vorher, wird der ausstehende Eintritt vor dem
Austritt verarbeitet, damit keine verspätete aktive Session zurückbleibt.

MOOSE kann für semantische Missionsobjekte, KI-Gruppen und Routen verwendet
werden. Es ist jedoch keine universelle Schnittstelle zur Bedienung der Avionik
eines Spielerflugzeugs.

### Erster DCS-Testpfad: Mission-Editor-Route

Bevor Navigraph-Routing und DTC-Erzeugung verfügbar sind, dient eine im DCS
Mission Editor angelegte Route als erster ausführbarer Flugplan. MOOSE übernimmt
die bestehende Gruppe als `FLIGHTGROUP`. Dabei gilt ausdrücklich die
Vererbungskette:

```text
FLIGHTGROUP -> OPSGROUP
```

Die Navigation darf deshalb die allgemeinen Zustände und Funktionen der
`OPSGROUP`-Basis nutzen und flugspezifische Informationen über `FLIGHTGROUP`
ergänzen. Dieser Testpfad ermöglicht ohne externe Navigationsdaten bereits:

- Mission-Editor-Wegpunkte und aktuellen Wegpunkt auslesen
- Sollroute mit Position, Kurs, Höhe und Geschwindigkeit vergleichen
- Flugphasen und Cross-Track-Abweichungen erproben
- Copilot- und Instructor-Hinweise testen
- Player-Session beim Einsteigen starten und beim Slot-Verlassen beenden
- später dieselbe neutrale Route mit Navigraph- und DTC-Adaptern vergleichen

Implementierter erster Routenabruf:

- Lua-Kommando `flightgroup.route.get`, Python-SDK
  `get_flightgroup_route(opsgroup_id, route_source="mission_editor")`.
- Die vollständige ME-Route stammt aus der geerbten `waypoints0`-Liste.
  `GetWaypoints()` liefert dagegen die bearbeitete aktuelle Route; MOOSE kann
  dort insbesondere den Landepunkt entfernen. Diese Quelle ist separat mit
  `route_source="current"` verfügbar.
- DCS-Wegpunkt-`x/y` sind horizontale Koordinaten und werden als Welt-`x/z`
  behandelt. `alt` (Meter), `alt_type` (BARO/RADIO) und `speed` (m/s) bleiben
  erhalten. Die F10-Darstellung verwendet nur die horizontale Projektion.
- `examples/sdk/monitor_player_aircraft.py` fragt die Route nach dem Einstieg
  ab und zeichnet die aufeinanderfolgenden Punkte als cyanfarbene Linie für
  die eigene Koalition. Mindestens zwei, höchstens 501 Punkte werden unterstützt.
  Beim Slot-Verlassen oder Skriptende wird nur dieses Overlay entfernt.
- Die Darstellung verändert weder die Route noch die Avionik. Sie verbindet
  lediglich Wegpunkte geradlinig und bildet noch keine Kurven, Holdings oder
  Instrumentenverfahren ab.

Live-Routenverfolgung im selben Python-Skript:

- Positionsabfrage der konkreten Spieler-`UNIT` alle zwei Sekunden über das
  vorhandene `object.coords`; kein zusätzlicher Lua-Timer.
- Entfernung zum nächsten Wegpunkt in NM und Peilung auf geografisch Nord.
  Kein magnetischer Steuerkurs und noch keine Windkorrektur.
- Seitliche Abweichung (XTE) in Metern zur aktiven geraden Segmentlinie:
  positiv rechts, negativ links. Berechnet in DCS-`x/z` passend zur F10-Linie;
  kein 3D-Schrägabstand. Vor/hinter dem Segment bezieht sie sich auf dessen
  verlängerte Linie, nicht auf den Abstand zum Endpunkt.
- Eigene deterministische Fortschrittsverfolgung ab WP 1 -> WP 2, konfigurierbar
  mit `INITIAL_TARGET_WAYPOINT`. Sie liest nicht die Avionik-Wegpunktauswahl aus.
- Umschalten beim Erreichen eines 500-m-Radius. Ein Überflug zwischen zwei
  Messungen zählt ebenfalls bei seitlicher Nähe und höchstens zehn Sekunden
  Messabstand. Keine automatische Übernahme eines weit voraus liegenden
  Wegpunkts beim ersten Positionssample.
- Zielpunkt erreicht bedeutet ausschließlich horizontale Nähe, nicht
  erfolgreiche Landung oder Einhaltung von Höhe und Geschwindigkeit.
- Die Positionsabfrage wird bei Leave, Missionsende und Skriptende abgebrochen.

Navigraph bildet überwiegend aktuelle reale zivile Navigation ab. DCS besitzt
eigene und teilweise historische Theaterdaten. Deshalb ist ein expliziter
Abgleich nötig. Ein identischer ICAO-Code garantiert nicht automatisch gleiche
Runways, Frequenzen, Verfahren oder Koordinaten.

### Ingame-Menü: erster Funktionstest

- MOOSE-Basis: `MENU_GROUP:New(group, text)` erstellt das Untermenü;
  `MENU_GROUP_COMMAND:New(group, text, parent, callback)` bindet die Aktionen.
- Testskript: `examples/sdk/monitor_player_menu.py`, direkt in VS Code starten,
  während der normale Python-Daemon und die DCS-Mission laufen. Nach dem
  Lua-Update die Mission einmal neu starten. Die Lua-Projektdatei wird zusätzlich
  ins MOOSE-Verzeichnis auf Branch `FF/PyBridge` synchronisiert.
- Funkmenü → F10 Other/Andere → **MoosePyBridge Test**; nicht die F10-Karte.
  **Nachricht anzeigen** nutzt `MESSAGE:ToGroup` direkt in Lua;
  **Python-Konsole** sendet `player.menu.selected` zur Ausgabe im Testskript.
- Die Menüs sind standardmäßig aus. Das Skript aktiviert sie per
  `player.menu.test.configure` für bereits besetzte und später betretene Gruppen.
  Eine `FLIGHTGROUP` oder ein Flug ist dafür nicht nötig.
- Wichtige Grenze: Gruppensichtbarkeit, keine personenbezogenen Berechtigungen.
  DCS liefert beim Klick keinen Spieler-Namen. `group_sessions` nennt deshalb
  nur die aktuellen Gruppenmitglieder, nicht den tatsächlichen Klickenden.
- Eine Menüinstanz je Gruppe; Entfernen erst beim letzten Slot-Austritt.
  Doppelte Leave-Events bleiben unterdrückt. Wiedereinstieg berücksichtigt eine
  geänderte DCS-Gruppen-ID. Entfernte Callbacks bleiben wirkungslos.
- Ctrl+C entfernt die Menüs dieses Skriptlaufs. Missionsende räumt ebenfalls auf
  und beendet das Skript. Hartes Beenden kann Menüs hinterlassen; ein neuer Lauf
  übernimmt den Test. Eine Lauf-ID verhindert Aufräumen durch einen älteren Lauf.
- Automatische Prüfung: Lua-Lifecycle-Test mit simulierten DCS-/MOOSE-Grenzen
  und Python-Tests für Ereignisempfang, Filter, Cursor und Aufräumen.
  Den Lua-Test über `MOOSEBRIDGE_TEST_LUA` auf einen lokalen Lua-Interpreter
  verweisen lassen. Beide Testaktionen wurden vom Benutzer in DCS bestätigt:
  Cockpitnachricht und `MENU CLICK` mit `GROUP:Test Hornet` / `funkyfranky`: PASS.

### Navigation über das Funkmenü

- Neuer normaler Einstieg: `examples/sdk/run_navigation_menu.py` in VS Code;
  Server unverändert weiterlaufen lassen, Mission nach Lua-Update neu starten.
  Das alte Menü-Testskript vorher beenden. Das neue Profil ersetzt das Testmenü.
- Funkmenü → F10 Other/Andere → **Navigation**, fünf Aktionen:
  **Route anzeigen**, **Route ausblenden**, **Navigationsstatus**,
  **Hinweise ein**, **Hinweise aus**.
- Route und Hinweise starten ausgeschaltet. Routenanzeige nutzt die erhaltene
  ME-Route und eine cyanfarbene F10-Linie für die eigene Koalition. Die Linie ist
  nicht nur für die Gruppe sichtbar. Ausblenden beeinflusst die Hinweise nicht.
- Status zeigt Referenzflugzeug, nächstes Ziel, NM-Entfernung, TRUE-Peilung und
  XTE per `MESSAGE:ToGroup`. Hinweise fragen standardmäßig alle zwei Sekunden ab
  und melden ungefähr alle zehn Sekunden sowie bei Wegpunkterfassung.
- Der vorhandene `RouteNavigator` wird pro Gruppen-Menüsitzung wiederverwendet;
  Fortschritt bleibt beim Aus-/Einblenden und beim Abschalten der Hinweise erhalten.
  Ohne Hinweise gibt es keine regelmäßigen Positionsabfragen. Kein Lesen oder
  Schreiben der Avionik-Wegpunktauswahl; Zielerfassung ist kein Landungsnachweis.
- Status/Hinweise verlangen genau ein Spielerflugzeug pro Gruppe und dessen
  FLIGHTGROUP. Mehrere Sitze desselben UNIT zählen als ein Flugzeug. Bei mehreren
  Spielerflugzeugen erfolgt eine Fehlermeldung statt einer willkürlichen Auswahl.
- Lua prüft bei Kontext-, Nachrichten- und Overlay-Aufrufen Besitzer-ID,
  Menüsitzungs-ID, DCS-Gruppen-ID und Belegung. Verspätete Aufträge einer alten
  Sitzung werden zurückgewiesen. Die letzte Person verlässt die Gruppe:
  `player.menu.closed`, Abbruch der Python-Hinweise, Entfernen der eigenen Linie.
- Lua räumt seine Linie auch ohne erreichbaren Python-Client auf. Ctrl+C,
  Missionsende oder ein neuer Menülauf entfernen das Menü und seine Linie;
  andere Overlays bleiben bestehen. Nach Missionsende das Skript neu starten.
- Prüfen am Boden: Linie ein/aus, Status, Hinweise ein (mindestens zehn Sekunden),
  Hinweise aus, Slot verlassen/wieder betreten und Ctrl+C. Automatische Tests
  decken Lua-Lifecycle/Schreibschutz und Python-Aktionen/Task-Abbruch ab;
  dieser neue Navigation-Menütest in DCS steht noch aus.

## DTC-Erkenntnisse

### Grundsätzliche Eignung

DCS kann DTCs im Mission Editor und im Spiel erzeugen, speichern, importieren
und exportieren. DTCs können:

- in einer `.miz` gespeichert werden
- einzelnen Player-/Client-Flugzeugen oder Flights zugeordnet werden
- als `.dtc` exportiert und später importiert werden
- vor Missionsstart ausgewählt werden
- am Boden auf einem freundlichen Flugplatz über das Ground-Crew-Menü verwaltet
  werden
- partitionsweise im Cockpit geladen werden

DTCs sind für Spieler-/Client-Flugzeuge gedacht. KI-Flugzeuge benötigen
weiterhin DCS- oder MOOSE-Routen.

### Aktueller Funktionsumfang

Die DTC-Unterstützung begann bei F-16C und F/A-18C und wurde auf MiG-29A
erweitert. AH-64D ist weit fortgeschritten, A-10C II ist geplant. Funktionen und
Speicheraufteilung sind flugzeugspezifisch.

Für die F-16C sind unter anderem relevant:

- Navigation Steerpoints und Routes
- VIP/VRP und Offset Aimpoints
- TACAN, ILS und Bingo
- Geo Lines, Steerpoints 31 bis 55
- Threat Points, Steerpoints 56 bis 70
- Destination Points, Steerpoints 81 bis 99

Für die F/A-18C sind unter anderem Navigation Points sowie SA-Daten wie CAP
Points, Corridors, FAOR/FLOT und Missile Engagement Zones relevant.

### Grenzen und Risiken

- Es ist derzeit keine stabile öffentliche DTC-API oder verbindliche
  Modul-übergreifende Dateispezifikation bekannt.
- ED- und Drittanbietermodule können unterschiedliche Datenmodelle und
  Oberflächen verwenden.
- Das Format und die DTC-Funktionen entwickeln sich schnell weiter.
- Ein DTC-Import kann bestehende Wegpunktslots überschreiben; ein generisches
  Merge-Verhalten darf nicht vorausgesetzt werden.
- Dynamic-Spawn-Workflows sind laut Forum noch nicht durchgehend zuverlässig.
- Eine dynamische Umplanung während eines laufenden Fluges ist nicht für jedes
  Modul oder jede Startart verfügbar.

Daher ist DTC ein Ausgabeadapter und ausdrücklich nicht das interne
Flugplanmodell.

### Geplanter Formatversuch

Sobald Zeit dafür ist, werden mit DCS mindestens diese Testdateien exportiert:

- `empty.dtc`: Default-DTC ohne eigene Navigationspunkte
- `one-point.dtc`: ein eindeutig benannter Wegpunkt
- `changed-point.dtc`: derselbe Punkt mit geänderter Koordinate und Höhe

Danach werden Dateityp, Serialisierung, Koordinaten, Partitionen, IDs,
Prüfsummen und Versionsabhängigkeiten untersucht. Der Versuch wird zuerst mit
der F/A-18C und danach optional mit der F-16C wiederholt.

## Vorgeschlagene Architektur

```text
Navigraph DFD ---------+
                       |
DCS/MOOSE Live State --+--> Normalisierung --> Navigationskern
                       |                         |
Aircraft Profiles -----+                         +--> Route/Procedure Planner
                                                 +--> Guidance/Monitoring
                                                 +--> Conflict Validation
                                                 |
                                                 +--> DTC Adapter je Modul
                                                 +--> MOOSE/DCS AI Route
                                                 +--> Copilot Tools
                                                 +--> Instructor/Evaluator
                                                 +--> Kneeboard/Mission Card
                                                 +--> später ATC Services
```

### Mögliche Kernmodelle

- `Airport`
- `Runway`
- `Navaid`
- `Waypoint`
- `AirwaySegment`
- `Airspace`
- `Procedure`
- `ProcedureLeg`
- `AltitudeConstraint`
- `SpeedConstraint`
- `Holding`
- `AircraftNavigationProfile`
- `FlightPlan`
- `RouteLeg`
- `NavigationSolution`
- `DcsMissionContext`
- `ThreatArea`
- `DtcCartridge`
- `DtcPartition`
- `FlightPhase`
- `AircraftTrainingProfile`
- `TrainingEvent`
- `TrainingSession`
- `DebriefingReport`

### Adaptergrenzen

- `NavigraphRepository`: DFD-Import und lokale Abfragen
- `DcsStateAdapter`: Wetter, Flugplätze, Beacons und Live-Zustand
- `MooseRouteAdapter`: semantische KI-Routen und Missionsbefehle
- `AircraftProfileRepository`: Leistung und Avionikgrenzen
- `DtcExporter`: Modul-spezifische Cartridge-Erzeugung
- `CockpitAdapter`: optionale direkte Avionikbedienung
- `FlightTelemetryAdapter`: Flugzustand und verfügbare Cockpitparameter
- `TrainingEvaluator`: deterministische Regeln, Toleranzen und Bewertungen
- `SimBriefAdapter`: optionaler OFP-Import

## Vorläufiger MVP

Der erste MVP soll ohne AI, Voice und direkte Cockpitbedienung funktionieren.
Die F/A-18C Hornet ist das erste Referenzflugzeug für Flugzeugprofil,
DTC-Adapter, Telemetrie und spätere Instructor-Funktionen.

### Funktionsumfang

1. DFD-v2-SQLite-Datenbank öffnen und Metadaten prüfen.
2. Airports, Runways, Navaids und Waypoints suchen.
3. Mehrdeutige Identifiers geografisch korrekt auflösen.
4. Start und Ziel mit einem DCS-Theater abgleichen.
5. eine Enroute-Verbindung über das Airway-Netz berechnen.
6. passende SID, STAR und Approach-Kandidaten bestimmen.
7. Procedure Legs und Constraints in einen neutralen Flugplan überführen.
8. Distanzen, Kurse und eine einfache ETA berechnen.
9. den Plan als JSON und lesbare Textdarstellung exportieren.
10. Tests mit bekannten Routen und Randfällen bereitstellen.

### Noch nicht Teil des ersten MVP

- vollständige Flugleistungsoptimierung
- Wetter- und NOTAM-Routing
- vollständige Terrain-Freigabe
- taktische Bedrohungsvermeidung
- Charts API
- automatische Cockpiteingabe
- AI-Copilot mit Schreibrechten
- ATC

## Entscheidungen

- Der Navigationskern wird deterministisch und unabhängig von einem LLM.
- Das Projekt wird als eigenständiges Python-Teilprojekt entwickelt, darf aber
  geeignete Transport-, Koordinaten-, Theater- und Zustandskomponenten aus
  MoosePyBridge wiederverwenden.
- Navigraph ist eine Datenquelle, nicht das Domänenmodell.
- DTC wird als flugzeugspezifisches Ausgabeformat behandelt.
- Die F/A-18C Hornet ist das erste Test- und Referenzflugzeug.
- Spieler-Sessions beginnen mit `PlayerEnterAircraft` und enden mit
  `PlayerLeaveUnit`; `FLIGHTGROUP` wird dabei als Spezialisierung der geerbten
  `OPSGROUP`-Basis behandelt.
- MOOSE bleibt der bevorzugte semantische Ausführungsweg für KI-Einheiten.
- Für Spielerflugzeuge werden DTC und später modulspezifische Cockpitadapter
  untersucht.
- Flight Instructor und Copilot bleiben getrennte Rollen. Der Instructor nutzt
  einen deterministischen Evaluator und das Sprachmodell nur für Erklärung und
  Dialog.
- AI-ATC beginnt, wenn überhaupt, mit ATIS und Advisory statt mit vollständiger
  Staffelungsverantwortung.

## Offene Fragen

- Soll das Teilprojekt im bestehenden Repository oder langfristig in einem
  eigenen Repository leben?
- Welche DCS-Karte bildet zusammen mit der F/A-18C den ersten vertikalen
  Prototyp?
- Beginnen wir mit zivilem IFR-Routing oder direkt mit taktischer
  Bedrohungsvermeidung?
- Welche DCS-Datenquellen stehen für Wetter, Runway und Funkfeuer zuverlässig
  zur Verfügung?
- Wie werden reale Navigraph-Airports und DCS-Flugplätze versioniert und
  abgeglichen?
- Welche Flugzeugleistungsdaten dürfen verwendet und verteilt werden?
- Soll die erste Oberfläche CLI, Browserkarte oder In-Game-Overlay sein?
- Welcher Teil einer Route darf automatisch geändert werden, nachdem der Pilot
  sie bestätigt hat?
- Welche Lizenzgrenzen gelten für die gewünschte Routendarstellung im Detail?
- Ist das exportierte `.dtc`-Format stabil und ohne DCS-interne Prüfsumme
  erzeugbar?
- Wie verhalten sich DTC-Import und Slot-Merge je Flugzeugmodul?

## Aufgabenliste

### Jetzt möglich

- [ ] Offizielle DFD-v2-Beispieldaten herunterladen und Lizenzhinweis
      dokumentieren.
- [ ] DFD-v2-SQLite-Schema gegen die Dokumentation inventarisieren.
- [ ] kleines Python-Experiment für Airport-, Navaid- und Waypoint-Suche bauen.
- [ ] neutralen `FlightPlan`- und `RouteLeg`-Entwurf erstellen.
- [x] F/A-18C Hornet als erstes Test- und Referenzflugzeug auswählen.
- [ ] erstes DCS-Theater für den MVP auswählen.
- [ ] vorhandene MoosePyBridge-Komponenten auf Wiederverwendbarkeit prüfen.
- [x] `PlayerEnterAircraft` und `PlayerLeaveUnit` in MoosePyBridge anbinden und
      aktive Spieler-Flugzeug-Sessions in Python spiegeln.
- [ ] Mission-Editor-Wegpunkte einer F/A-18C-`FLIGHTGROUP` als ersten Flugplan
      einlesen und über die geerbte `OPSGROUP`-Basis beobachten.
- [x] Read-only-Routenabruf und F10-Linienanzeige im Python-Testskript implementieren.
- [x] F10-Linienverlauf einschließlich Start-/Landepunkt live gegen die
      Mission-Editor-Route prüfen.
- [x] Live-Entfernung, True-Peilung und XTE mit eigener Wegpunktsequenz implementieren.
- [ ] Wegpunktwechsel und Links-/Rechts-Abweichungen im Flug live prüfen.
- [x] Opt-in-Gruppenmenü mit Cockpitnachricht und Python-Konsolenausgabe implementieren.
- [x] Beide einfachen Menüaktionen in DCS live bestätigen.
- [x] Navigation-Menü für Routenanzeige, Status und ein-/ausschaltbare Hinweise anbinden.
- [ ] Navigation-Menü am Boden inklusive Entfernen und Wiedereinstieg live prüfen.
- [ ] Testfälle für identische Fix-Identifiers und DCS/Navigraph-Abweichungen
      definieren.

### Nach Navigraph-Freigabe

- [ ] Client ID und Client Secret ausschließlich lokal konfigurieren.
- [ ] Device Authorization Flow mit PKCE implementieren.
- [ ] sicheren, atomaren Token-Store implementieren.
- [ ] `packages`-Endpoint anbinden.
- [ ] Cycle-, Revision- und SHA-256-Prüfung implementieren.
- [ ] Subscription- und Fehlerzustände verständlich behandeln.
- [ ] aktuellen DFD-v2-Datensatz laden und mit dem Sample vergleichen.

### Nach Erzeugung der DTC-Testdateien

- [ ] `.dtc`-Dateityp und Struktur bestimmen.
- [ ] kontrollierte Diffs der drei F/A-18C-Dateien erstellen.
- [ ] Koordinaten-, Höhen-, Namens- und Slotkodierung identifizieren.
- [ ] Import einer extern reproduzierten Testdatei in DCS validieren.
- [ ] Versuch optional mit F-16C wiederholen.
- [ ] Formatversion und DCS-Build in Test-Fixtures speichern.
- [ ] Entscheidung über einen ersten read-only oder write-fähigen DTC-Adapter
      treffen.

### Später

- [ ] Airway-Router und Procedure Resolver entwickeln.
- [ ] DCS-Live-Wetter und Runway-Auswahl anbinden.
- [ ] Aircraft Navigation Profiles definieren.
- [ ] F/A-18C-DTC-Exporter entwickeln.
- [ ] MOOSE-Route-Exporter entwickeln.
- [ ] Guidance- und Monitoring-Service entwickeln.
- [ ] Advisory-Copilot als Tool-Consumer anbinden.
- [ ] F/A-18C-Trainingsprofil und Flugphasenerkennung entwickeln.
- [ ] regelbasierten Instructor-Evaluator mit Toleranzen und Hysterese
      entwickeln.
- [ ] IFR-/Anflug-Instructor und Debriefing-Bericht prototypisieren.
- [ ] Sensor- und Waffensystemkurse modular ergänzen.
- [ ] ATIS-Prototyp evaluieren.
- [ ] erst danach Tower-/Approach-ATC evaluieren.

## Referenzen

- [Navigraph Developer Portal](https://developers.navigraph.com/docs/general/introduction)
- [Navigraph API Access Request](https://developers.navigraph.com/docs/request-access)
- [Navigraph Navigation Data API](https://developers.navigraph.com/docs/navigation-data/api-overview)
- [Navigraph DFD v2 Specification](https://developers.navigraph.com/docs/navigation-data/dfd-data-format-v2)
- [Navigraph Sample Data](https://developers.navigraph.com/docs/navigation-data/sample-data)
- [Navigraph Device Authorization Flow](https://developers.navigraph.com/docs/authentication/device-authorization)
- [Navigraph Restrictions](https://developers.navigraph.com/docs/general/restrictions)
- [DCS DTC Forum](https://forum.dcs.world/forum/1329-dtc-data-transfer-cartridge/)
- [DCS DTC Quick Start Guide](https://forum.dcs.world/topic/371995-quick-start-guide-data-transfer-cartridge-dtc/)
- [DCS 2026 Roadmap](https://www.digitalcombatsimulator.com/en/news/2026-01-09/)
- [DCS AH-64D DTC Development Report](https://www.digitalcombatsimulator.com/en/news/2026-08-07/)

import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import pandas as pd
import json
import os

# KONŠTANTY SPU NITRA (Metodický pokyn 1/2023)
FOND_CASU = 1537.5
VAHA_VZDELAVANIE = 0.40
VAHA_PUBLIKACIE = 0.40
VAHA_PROJEKTY = 0.20
DB_FILE = "databaza_pracovnikov.json"

class SPUZatazApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SPU Nitra - Hodnotenie pracovnej záťaže")
        self.root.geometry("1050x720")
        self.importovane_data = None
        self.create_widgets()
        self.nacitat_databazu()
        
    def create_widgets(self):
        # --- REŽIM 1: FORMULÁR PRE MANUÁLNE ZADÁVANIE (SÁM SI ZADÁVAM VSTUPY) ---
        form_frame = tk.LabelFrame(self.root, text=" REŽIM 1: Manuálne zadávanie vstupných údajov (Vlastný výpočet) ", padx=10, pady=10, font=("Arial", 10, "bold"), fg="#1e4620")
        form_frame.pack(fill="x", padx=15, pady=10)
        
        # Riadok 1
        tk.Label(form_frame, text="Meno a priezvisko:").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.entry_name = tk.Entry(form_frame, width=25)
        self.entry_name.grid(row=0, column=1, padx=5, pady=2)
        
        tk.Label(form_frame, text="Skóre Publikácie (body):").grid(row=0, column=2, sticky="w", padx=2, pady=2)
        self.entry_pub = tk.Entry(form_frame, width=15)
        self.entry_pub.grid(row=0, column=3, padx=5, pady=2)
        
        # Riadok 2
        tk.Label(form_frame, text="Odučené hodiny výučby:").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        self.entry_edu_hours = tk.Entry(form_frame, width=25)
        self.entry_edu_hours.grid(row=1, column=1, padx=5, pady=2)
        
        tk.Label(form_frame, text="Počet študentov na priamej výučbe:").grid(row=1, column=2, sticky="w", padx=2, pady=2)
        self.entry_students = tk.Entry(form_frame, width=15)
        self.entry_students.grid(row=1, column=3, padx=5, pady=2)
        
        # Riadok 3
        tk.Label(form_frame, text="Vedené záverečné práce Bc./Ing. (ks):").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        self.entry_zp_bc_ing = tk.Entry(form_frame, width=25)
        self.entry_zp_bc_ing.grid(row=2, column=1, padx=5, pady=2)
        self.entry_zp_bc_ing.insert(0, "0")
        
        tk.Label(form_frame, text="Vedené práce PhD. (ks):").grid(row=2, column=2, sticky="w", padx=2, pady=2)
        self.entry_zp_phd = tk.Entry(form_frame, width=15)
        self.entry_zp_phd.grid(row=2, column=3, padx=5, pady=2)
        self.entry_zp_phd.insert(0, "0")
        
        # Riadok 4
        tk.Label(form_frame, text="Základné hodiny na projektoch (UIS):").grid(row=3, column=0, sticky="w", padx=2, pady=2)
        self.entry_prj_hours = tk.Entry(form_frame, width=25)
        self.entry_prj_hours.grid(row=3, column=1, padx=5, pady=2)
        
        self.var_zodpovedny = tk.BooleanVar()
        self.chk_zodpovedny = tk.Checkbutton(form_frame, text="Zodpovedný riešiteľ výskumného projektu (2x bonifikácia hodín)", variable=self.var_zodpovedny, font=("Arial", 9, "italic"))
        self.chk_zodpovedny.grid(row=3, column=2, columnspan=2, sticky="w", padx=2, pady=2)
        
        # Riadok 5: Tlačidlo pre výpočet manuálnych dát
        add_btn = tk.Button(form_frame, text="Vypočítať a uložiť do DB", bg="#4CAF50", fg="white", font=("Arial", 9, "bold"), command=self.add_manual_data)
        add_btn.grid(row=4, column=3, pady=5, sticky="e")

        # --- REŽIM 2: SÚBOROVÝ IMPORT A EXPORT (ZADÁVANIE CEZ EXCEL) ---
        file_frame = tk.LabelFrame(self.root, text=" REŽIM 2: Hromadné zadávanie údajov a správa databázy (Excel / Export) ", padx=10, pady=10, font=("Arial", 10, "bold"), fg="#1c4966")
        file_frame.pack(fill="x", padx=15, pady=5)
        
        import_btn = tk.Button(file_frame, text="📁 Aktualizovať databázu z Excelu (.xlsx)", bg="#008CBA", fg="white", font=("Arial", 9, "bold"), command=self.load_file)
        import_btn.pack(side="left", padx=5)
        
        self.export_btn = tk.Button(file_frame, text="📥 Exportovať celú databázu do Excelu", bg="#4CAF50", fg="white", font=("Arial", 9, "bold"), command=self.export_to_excel)
        self.export_btn.pack(side="left", padx=10)
        
        clear_btn = tk.Button(file_frame, text="❌ Vymazať celú databázu", bg="#f44336", fg="white", font=("Arial", 9), command=self.vymazat_db_subor)
        clear_btn.pack(side="right", padx=5)

        # --- TABUĽKA VÝSLEDKOV (ZOBRAZENIE DATABÁZY) ---
        table_frame = tk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=15, pady=10)
        
        columns = ("meno", "hod_edu", "hod_prj", "skore", "vytazenie", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.tree.heading("meno", text="Meno a priezvisko")
        self.tree.heading("hod_edu", text="Hod. Vzdelávanie")
        self.tree.heading("hod_prj", text="Hod. Projekty")
        self.tree.heading("skore", text="Celkové Skóre (40:40:20)")
        self.tree.heading("vytazenie", text="Vyťaženie fondu")
        self.tree.heading("status", text="Status záťaže (Čl. 7)")
        
        self.tree.column("meno", width=200)
        self.tree.column("hod_edu", width=120, anchor="center")
        self.tree.column("hod_prj", width=110, anchor="center")
        self.tree.column("skore", width=150, anchor="center")
        self.tree.column("vytazenie", width=120, anchor="center")
        self.tree.column("status", width=250)
        self.tree.pack(fill="both", expand=True)

    def spocitaj_zataz_spu(self, hod_vyucba, pocet_studentov, bc_ing_prace, phd_prace, hod_projekty, je_zodpovedny):
        # Článok 7, bod 1.1: Výpočet ročnej hodinovej záťaže vzdelávania
        celkove_hod_edu = (2 * hod_vyucba) + (0.25 * pocet_studentov) + (26 * bc_ing_prace) + (312 * phd_prace)
        
        # Článok 5, bod 1.A: Zodpovedný riešiteľ výskumného projektu získava 2x hodín
        koef_riesitel = 2 if je_zodpovedny else 1
        celkove_hod_prj = hod_projekty * koef_riesitel
        
        # Celkové ročné vyťaženie pedagogického fondu voči limitu 1537.5 hodín
        pct_vytazenia = ((celkove_hod_edu + celkove_hod_prj) / FOND_CASU) * 100
        
        if pct_vytazenia > 100: status = "Kritické preťaženie (>100%)"
        elif pct_vytazenia >= 80: status = "Vysoká záťaž (Nutné posúdenie)"
        elif 40 <= pct_vytazenia <= 60: status = "Ideálny stav (40% - 60%)"
        elif pct_vytazenia < 40: status = "Poddimenzovaná záťaž (<40%)"
        else: status = "Štandardná záťaž"
        
        return celkove_hod_edu, celkove_hod_prj, round(pct_vytazenia, 2), status

    def prekreslit_tabulku(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        if self.importovane_data is not None:
            for _, row in self.importovane_data.iterrows():
                self.tree.insert("", "end", values=(
                    row['Meno a priezvisko'], 
                    f"{row['Vzdelávanie (hodiny)']} h", 
                    f"{row['Projekty (hodiny)']} h", 
                    row['Celkové Skóre'], 
                    f"{row['Vyťaženie (%)']} %", 
                    row['Status']
                ))

    def nacitat_databazu(self):
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    self.importovane_data = pd.DataFrame(json.load(f))
                    self.prekreslit_tabulku()
            except Exception as e: messagebox.showerror("Chyba DB", str(e))
        else:
            self.importovane_data = pd.DataFrame(columns=['Meno a priezvisko', 'Vzdelávanie (hodiny)', 'Projekty (hodiny)', 'Skóre publikácie', 'Celkové Skóre', 'Vyťaženie (%)', 'Status'])

    def ulozit_databazu(self):
        if self.importovane_data is not None:
            try:
                with open(DB_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.importovane_data.to_dict(orient="records"), f, ensure_ascii=False, indent=4)
            except Exception as e: messagebox.showerror("Chyba DB", str(e))

    def vymazat_db_subor(self):
        if messagebox.askyesno("Pozor", "Naozaj chcete natvrdo vymazať celú lokálnu databázu?"):
            if os.path.exists(DB_FILE): os.remove(DB_FILE)
            self.nacitat_databazu()

    def add_manual_data(self):
        try:
            name = self.entry_name.get().strip()
            s_pub = float(self.entry_pub.get().replace(',', '.'))
            h_vyucba = float(self.entry_edu_hours.get().replace(',', '.'))
            students = float(self.entry_students.get().replace(',', '.'))
            bc_ing = float(self.entry_zp_bc_ing.get().replace(',', '.'))
            phd = float(self.entry_zp_phd.get().replace(',', '.'))
            h_projekty = float(self.entry_prj_hours.get().replace(',', '.'))
            
            if not name: raise ValueError("Meno nesmie byť prázdne.")
            
            # Výpočet hodín na základe REŽIMU 1 (Manuálne vstupy)
            hod_edu, hod_prj, pct, status = self.spocitaj_zataz_spu(h_vyucba, students, bc_ing, phd, h_projekty, self.var_zodpovedny.get())
            
            # Celkové sumárne skóre podla váhového pomeru 40:40:20
            celkove_skore = (hod_edu * VAHA_VZDELAVANIE) + (s_pub * VAHA_PUBLIKACIE) + (hod_prj * VAHA_PROJEKTY)
            celkove_skore = round(celkove_skore, 4)
            
            novy_riadok = {
                'Meno a priezvisko': name, 'Vzdelávanie (hodiny)': hod_edu, 'Projekty (hodiny)': hod_prj,
                'Skóre publikácie': s_pub, 'Celkové Skóre': celkove_skore, 'Vyťaženie (%)': pct, 'Status': status
            }
            
            # Ak zamestnanec v databáze už existuje, prepíšeme ho novými údajmi
            if name in self.importovane_data['Meno a priezvisko'].values:
                self.importovane_data = self.importovane_data[self.importovane_data['Meno a priezvisko'] != name]
                

import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import pandas as pd
import json
import os

FOND_CASU, VAHA_VZDELAVANIE, VAHA_PUBLIKACIE, VAHA_PROJEKTY = 1537.5, 0.40, 0.40, 0.20
DB_FILE = "databaza_pracovnikov.json"

class SPUZatazApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SPU Nitra - Hodnotenie a evidencia pracovnej záťaže")
        self.root.geometry("1200x750")
        self.importovane_data = None
        self.create_widgets()
        self.nacitat_databazu()
        
    def create_widgets(self):
        form_frame = tk.LabelFrame(self.root, text=" Evidencia akademických pracovníkov a vstupov ", padx=10, font=("Arial", 10, "bold"), fg="#1e4620")
        form_frame.pack(fill="x", padx=15, pady=10)
        
        fields = [
            ("Titul pred menom:", "entry_titul_pred", 0, 0), ("Meno a priezvisko *:", "entry_name", 0, 2), ("Titul za menom:", "entry_titul_za", 0, 4),
            ("Fakulta:", "entry_fakulta", 1, 0), ("Ústav:", "entry_ustav", 1, 2), ("Katedra:", "entry_katedra", 1, 4),
            ("Hodiny výučby:", "entry_edu_hours", 2, 0), ("Počet študentov:", "entry_students", 2, 2), ("Skóre Publikácie:", "entry_pub", 2, 4),
            ("Práce Bc./Ing.:", "entry_zp_bc_ing", 3, 0), ("Práce PhD.:", "entry_zp_phd", 3, 2), ("Hodiny projekty:", "entry_prj_hours", 3, 4)
        ]
        for lbl, attr, r, c in fields:
            tk.Label(form_frame, text=lbl).grid(row=r, column=c, sticky="w", padx=2, pady=2)
            setattr(self, attr, tk.Entry(form_frame, width=20))
            getattr(self, attr).grid(row=r, column=c+1, padx=5, pady=2)
            if attr in ["entry_edu_hours", "entry_students", "entry_pub", "entry_zp_bc_ing", "entry_zp_phd", "entry_prj_hours"]:
                getattr(self, attr).insert(0, "0")

        self.var_zodpovedny = tk.BooleanVar()
        tk.Checkbutton(form_frame, text="Zodpovedný riešiteľ projektu (2x hodiny)", variable=self.var_zodpovedny).grid(row=4, column=0, columnspan=3, sticky="w")
        tk.Button(form_frame, text="Vypočítať a uložiť", bg="#4CAF50", fg="white", font=("Arial", 9, "bold"), command=self.add_manual_data).grid(row=4, column=5, sticky="e")

        file_frame = tk.LabelFrame(self.root, text=" Súborové operácie ", padx=10, pady=10, font=("Arial", 10, "bold"), fg="#1c4966")
        file_frame.pack(fill="x", padx=15, pady=5)
        tk.Button(file_frame, text="📁 Importovať z Excelu", bg="#008CBA", fg="white", command=self.load_file).pack(side="left", padx=5)
        tk.Button(file_frame, text="📥 Exportovať DB", bg="#4CAF50", fg="white", command=self.export_to_excel).pack(side="left", padx=10)
        tk.Button(file_frame, text="❌ Resetovať DB", bg="#f44336", fg="white", command=self.vymazat_db_subor).pack(side="right", padx=5)

        table_frame = tk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=15, pady=10)
        self.cols = ("titul_pred", "meno", "titul_za", "fakulta", "ustav", "katedra", "s_edu", "s_pub", "s_prj", "skore", "vytazenie", "status")
        self.tree = ttk.Treeview(table_frame, columns=self.cols, show="headings")
        for col in self.cols: self.tree.heading(col, text=col.replace('_', ' ').capitalize()); self.tree.column(col, width=90, anchor="center")
        self.tree.pack(fill="both", expand=True)

    def spocitaj_zataz_spu(self, hod_vyucba, pocet_studentov, bc_ing, phd, hod_prj, je_zodpovedny):
        h_edu = (2 * hod_vyucba) + (0.25 * pocet_studentov) + (26 * bc_ing) + (312 * phd)
        h_prj = hod_prj * (2 if je_zodpovedny else 1)
        pct = round(((h_edu + h_prj) / FOND_CASU) * 100, 2)
        status = "Kritické preťaženie" if pct > 100 else "Vysoká záťaž" if pct >= 80 else "Ideálny stav" if 40 <= pct <= 60 else "Poddimenzovaná" if pct < 40 else "Štandardná"
        return h_edu, h_prj, pct, status

    def prekreslit_tabulku(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        if self.importovane_data is not None:
            for _, r in self.importovane_data.iterrows():
                self.tree.insert("", "end", values=(r.get('Titul pred menom',''), r.get('Meno a priezvisko',''), r.get('Titul za menom',''), r.get('Fakulta',''), r.get('Ústav',''), r.get('Katedra',''), f"{r.get('Skóre vzdelávanie',0)} h", r.get('Skóre publikácie',0), f"{r.get('Skóre projekty',0)} h", r.get('Celkové Skóre',0), f"{r.get('Vyťaženie (%)',0)} %", r.get('Status','')))

    def nacitat_databazu(self):
        if os.path.exists(DB_FILE):
            try: self.importovane_data = pd.DataFrame(json.load(open(DB_FILE, "r", encoding="utf-8"))); self.prekreslit_tabulku()
            except Exception as e: messagebox.showerror("Chyba DB", str(e))
        else: self.importovane_data = pd.DataFrame(columns=['Titul pred menom', 'Meno a priezvisko', 'Titul za menom', 'Fakulta', 'Ústav', 'Katedra', 'Skóre vzdelávanie', 'Skóre publikácie', 'Skóre projekty', 'Celkové Skóre', 'Vyťaženie (%)', 'Status'])

    def ulozit_databazu(self):
        if self.importovane_data is not None: json.dump(self.importovane_data.to_dict(orient="records"), open(DB_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=4)

    def vymazat_db_subor(self):
        if messagebox.askyesno("Pozor", "Vymazať databázu?") and os.path.exists(DB_FILE): os.remove(DB_FILE); self.nacitat_databazu()

    def add_manual_data(self):
        try:
            name = self.entry_name.get().strip()
            if not name: raise ValueError("Meno je povinné.")
            s_pub = float(self.entry_pub.get().replace(',', '.'))
            h_vy = float(self.entry_edu_hours.get().replace(',', '.'))
            st = float(self.entry_students.get().replace(',', '.'))
            bc = float(self.entry_zp_bc_ing.get().replace(',', '.'))
            ph = float(self.entry_zp_phd.get().replace(',', '.'))
            hp = float(self.entry_prj_hours.get().replace(',', '.'))
            h_edu, h_prj, pct, status = self.spocitaj_zataz_spu(h_vy, st, bc, ph, hp, self.var_zodpovedny.get())
            skore = round((h_edu * VAHA_VZDELAVANIE) + (s_pub * VAHA_PUBLIKACIE) + (h_prj * VAHA_PROJEKTY), 4)
            novy = {'Titul pred menom': self.entry_titul_pred.get().strip(), 'Meno a priezvisko': name, 'Titul za menom': self.entry_titul_za.get().strip(), 'Fakulta': self.entry_fakulta.get().strip(), 'Ústav': self.entry_ustav.get().strip(), 'Katedra': self.entry_katedra.get().strip(), 'Skóre vzdelávanie': h_edu, 'Skóre publikácie': s_pub, 'Skóre projekty': h_prj, 'Celkové Skóre': skore, 'Vyťaženie (%)': pct, 'Status': status}
            if name in self.importovane_data['Meno a priezvisko'].values: self.importovane_data = self.importovane_data[self.importovane_data['Meno a priezvisko'] != name]
            self.importovane_data = pd.concat([self.importovane_data, pd.DataFrame([novy])], ignore_index=True)
            self.ulozit_databazu(); self.prekreslit_tabulku()
        except Exception as e: messagebox.showerror("Chyba", str(e))

    def load_file(self):
        fp = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if not fp: return
        try:
            df = pd.read_excel(fp)
            for _, row in df.iterrows():
                meno = row.get('Meno a priezvisko', 'Neznámy')
                if not meno or pd.isna(meno): continue
                s_edu = float(str(row.get('Skóre vzdelávanie', 0)).replace(',', '.'))
                s_pub = float(str(row.get('Skóre publikácie', 0)).replace(',', '.'))
                s_prj = float(str(row.get('Skóre projekty', 0)).replace(',', '.'))
                pct = round((s_edu / FOND_CASU) * 100, 2)
                skore = round((s_edu * VAHA_VZDELAVANIE) + (s_pub * VAHA_PUBLIKACIE) + (s_prj * VAHA_PROJEKTY), 4)
                status = "Ideálny stav" if 40 <= pct <= 60 else "Vysoká záťaž" if pct >= 80 else "Štandardná"
                novy = {'Titul pred menom': row.get('Titul pred menom', ''), 'Meno a priezvisko': meno, 'Titul za menom': row.get('Titul za menom', ''), 'Fakulta': row.get('Fakulta', ''), 'Ústav': row.get('Ústav', ''), 'Katedra': row.get('Katedra', ''), 'Skóre vzdelávanie': s_edu, 'Skóre publikácie': s_pub, 'Skóre projekty': s_prj, 'Celkové Skóre': skore, 'Vyťaženie (%)': pct, 'Status': status}
                if meno in self.importovane_data['Meno a priezvisko'].values: self.importovane_data = self.importovane_data[self.importovane_data['Meno a priezvisko'] != meno]
                self.importovane_data = pd.concat([self.importovane_data, pd.DataFrame([novy])], ignore_index=True)
            self.ulozit_databazu(); self.prekreslit_tabulku(); messagebox.showinfo("Úspech", "Import hotový.")
        except Exception as e: messagebox.showerror("Chyba Excelu", str(e))

    def export_to_excel(self):
        if self.importovane_data is None or self.importovane_data.empty: return
        sp = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if sp: self.importovane_data.to_excel(sp, index=False); messagebox.showinfo("Export", "Uložené.")

if __name__ == "__main__":
    root = tk.Tk()
    app = SPUZatazApp(root)
    root.mainloop()
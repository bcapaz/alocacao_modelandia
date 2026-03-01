import streamlit as st
import pandas as pd
import numpy as np
import unicodedata
import difflib

# --- Configuração da Página ---
st.set_page_config(page_title="Alocador de Delegações", page_icon="🌍", layout="wide")
st.title("🌍 Alocador de Delegações Universal")
st.markdown("Sistema de alocação automática para Modelos Diplomáticos. Funciona com qualquer form e planilha!")

# --- Funções Auxiliares ---
def normalize_text(text):
    if pd.isna(text):
        return ""
    text = str(text).upper().strip()
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
    return text

def find_best_match(requested_del, committee_code, available_delegations):
    if not requested_del or committee_code not in available_delegations:
        return None
    req_norm = normalize_text(requested_del)
    req_norm_clean = req_norm.split('-')[0].strip()
    available = available_delegations[committee_code]
    avail_norm = [normalize_text(d) for d in available]
    
    for idx, an in enumerate(avail_norm):
        if an == req_norm: return available[idx]
    for idx, an in enumerate(avail_norm):
        if req_norm in an or an in req_norm: return available[idx]
        if req_norm_clean and (req_norm_clean in an or an in req_norm_clean): return available[idx]
            
    matches = difflib.get_close_matches(req_norm, avail_norm, n=1, cutoff=0.6)
    if matches:
        idx = avail_norm.index(matches[0])
        return available[idx]
    return None

# --- ETAPA 1: Upload de Arquivos ---
st.header("📂 Etapa 1: Upload dos Arquivos")
col1, col2 = st.columns(2)

with col1:
    st.subheader("Vagas (Planilha de Delegações)")
    del_file = st.file_uploader("Upload do Excel com as vagas", type=['xlsx'])

with col2:
    st.subheader("Inscrições (Forms)")
    insc_files = st.file_uploader("Upload do(s) Excel(s) de respostas", type=['xlsx'], accept_multiple_files=True)

if del_file and insc_files:
    # 1. Lê as Delegações
    delegacoes_df = pd.read_excel(del_file)
    available_delegations = {}
    colunas_vagas = delegacoes_df.columns.tolist() # Para o menu de mapeamento
    
    for col in colunas_vagas:
        dels = delegacoes_df[col].dropna().astype(str).str.strip().tolist()
        available_delegations[normalize_text(col)] = [d.strip() for d in dels if d.strip()]

    # 2. Lê e Junta as Inscrições
# 2. Lê e Junta as Inscrições (Leitura Inteligente)
    dfs = []
    for f in insc_files:
        # Tenta ler o arquivo normalmente
        df = pd.read_excel(f)
        df.columns = df.columns.astype(str).str.strip() # Remove espaços invisíveis
        
        # Se não achar a coluna de tempo, tenta pular as 3 linhas (para arquivos antigos com Legenda)
        colunas_tempo = ['Carimbo de data/hora', 'Timestamp', 'Data/Hora']
        if not any(col in df.columns for col in colunas_tempo):
            df = pd.read_excel(f, skiprows=3)
            df.columns = df.columns.astype(str).str.strip()
            
        # Padroniza a coluna para o código não se perder
        for col in colunas_tempo:
            if col in df.columns:
                df.rename(columns={col: 'Carimbo de data/hora'}, inplace=True)
                break
                
        dfs.append(df)
    
    inscricoes_df = pd.concat(dfs, ignore_index=True)
    inscricoes_df = inscricoes_df.sort_values(by='Carimbo de data/hora')

    st.success(f"Arquivos carregados! Encontradas {len(inscricoes_df)} inscrições.")
    st.divider()

    # --- ETAPA 2: Mapeamento Dinâmico dos Comitês ---
    st.header("🔗 Etapa 2: Mapeamento de Comitês")
    st.write("Como cada modelo tem nomes diferentes, associe o nome do comitê que aparece no formulário com a coluna correspondente na planilha de vagas.")
    
    # Extrai todos os comitês únicos que as pessoas escolheram no formulário
    comites_form = set()
    for i in range(1, 6):
        col_name = f'{i}ª opção de comitê:'
        if col_name in inscricoes_df.columns:
            comites_form.update(inscricoes_df[col_name].dropna().unique())
    
    comites_form = sorted([str(c) for c in comites_form if str(c).strip()])
    
    committee_map = {}
    map_cols = st.columns(2)
    
    # Cria os menus suspensos para o usuário cruzar os dados
    opcoes_vagas = ["-- Ignorar / Não Mapear --"] + colunas_vagas
    
    for i, comite in enumerate(comites_form):
        with map_cols[i % 2]:
            escolha = st.selectbox(f"Comitê no Forms: **{comite}**", opcoes_vagas, key=f"map_{comite}")
            if escolha != "-- Ignorar / Não Mapear --":
                # Salva o mapeamento normalizado
                committee_map[normalize_text(comite)] = normalize_text(escolha)

    st.divider()

    # --- ETAPA 3: Delegados Estrela ---
    st.header("🌟 Etapa 3: Delegados Estrela (Prioridade)")
    st.write("Selecione os delegados que o Secretariado já definiu (eles furam a fila da alocação).")
    
    todos_nomes = inscricoes_df['Nome completo:'].dropna().unique().tolist()
    delegados_estrela = st.multiselect("Pesquise e selecione os Delegados:", todos_nomes)
    
    config_estrelas = {}
    if delegados_estrela:
        cols_star = st.columns(3)
        for i, nome in enumerate(delegados_estrela):
            with cols_star[i % 3]:
                opcao = st.selectbox(f"Atender qual opção de {nome}?", [1, 2, 3, 4, 5], key=f"opt_{nome}")
                config_estrelas[nome] = opcao
                
    st.divider()

    # --- ETAPA 4: Processamento ---
    if st.button("🚀 Processar Alocação Automática", type="primary", use_container_width=True):
        allocated = []
        pre_allocated_names = set()

        # 1. Aloca as Estrelas primeiro
        for nome in delegados_estrela:
            person_row = inscricoes_df[inscricoes_df['Nome completo:'] == nome].iloc[0]
            opcao_escolhida = config_estrelas[nome]
            
            comite_col = f'{opcao_escolhida}ª opção de comitê:'
            del_col = f'{opcao_escolhida}ª opção de delegação:'
            
            if not pd.isna(person_row.get(comite_col)) and not pd.isna(person_row.get(del_col)):
                c_code = committee_map.get(normalize_text(person_row[comite_col]), None)
                if c_code:
                    match = find_best_match(person_row[del_col], c_code, available_delegations)
                    if match:
                        allocated.append({
                            'Timestamp': person_row['Carimbo de data/hora'],
                            'Nome': nome,
                            'Dupla': person_row.get('Nome completo da dupla (se houver):', ""),
                            'Comitê Alocado': c_code.upper(),
                            'Delegação Alocada': match,
                            'Opção Atendida': f"{opcao_escolhida} (ESTRELA)"
                        })
                        available_delegations[c_code].remove(match)
                        pre_allocated_names.add(nome)

        # 2. Aloca o resto por ordem de chegada
        for index, row in inscricoes_df.iterrows():
            name = row['Nome completo:']
            if pd.isna(name) or name in pre_allocated_names:
                continue
            
            allocation, alloc_comite, alloc_option = None, None, None
            
            for i in range(1, 6):
                comite_col = f'{i}ª opção de comitê:'
                del_col = f'{i}ª opção de delegação:'
                
                if comite_col not in row or del_col not in row: continue
                if pd.isna(row[comite_col]) or pd.isna(row[del_col]): continue
                    
                c_code = committee_map.get(normalize_text(row[comite_col]), None)
                if not c_code: continue
                    
                match = find_best_match(row[del_col], c_code, available_delegations)
                if match:
                    allocation, alloc_comite, alloc_option = match, c_code.upper(), i
                    available_delegations[c_code].remove(match)
                    break
                    
            allocated.append({
                'Timestamp': row['Carimbo de data/hora'],
                'Nome': name,
                'Dupla': row.get('Nome completo da dupla (se houver):', "") if not pd.isna(row.get('Nome completo da dupla (se houver):')) else "",
                'Comitê Alocado': alloc_comite if alloc_comite else "NÃO ALOCADO",
                'Delegação Alocada': allocation if allocation else "NÃO ALOCADO",
                'Opção Atendida': alloc_option if alloc_option else "N/A"
            })

        # --- Exibe Resultados ---
        allocated_df = pd.DataFrame(allocated)
        st.header("📊 Resultados Finais")
        
        tab1, tab2 = st.tabs(["✅ Sucesso (Alocados)", "⚠️ Ficaram sem Vaga"])
        
        with tab1:
            st.dataframe(allocated_df[allocated_df['Comitê Alocado'] != 'NÃO ALOCADO'], use_container_width=True)
            
        with tab2:
            nao_alocados_df = allocated_df[allocated_df['Comitê Alocado'] == 'NÃO ALOCADO']
            if len(nao_alocados_df) > 0:
                st.warning(f"Atenção: {len(nao_alocados_df)} inscritos não conseguiram vaga em nenhuma das opções preenchidas.")
                st.dataframe(nao_alocados_df, use_container_width=True)
            else:
                st.success("Perfeito! Todos os inscritos foram alocados com sucesso.")

        # Botão para Baixar
        csv = allocated_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(
            label="📥 Baixar Planilha Final de Alocação",
            data=csv,
            file_name='alocacao_final.csv',
            mime='text/csv',
            type="primary"
        )
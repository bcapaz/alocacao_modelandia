import streamlit as st
import pandas as pd
import numpy as np
import unicodedata
import difflib

# --- Configuração da Página ---
st.set_page_config(page_title="Alocador Interativo", page_icon="🌍", layout="wide")

# --- Variáveis de Memória (Estado da Sessão) ---
if 'status' not in st.session_state:
    st.session_state.status = 'setup' # setup, processing, resolving, finished
    st.session_state.allocated = []
    st.session_state.current_idx = 0
    st.session_state.available_delegations = {}
    st.session_state.pre_allocated_names = set()
    st.session_state.person_to_resolve = None
    st.session_state.inscricoes_df = None
    st.session_state.committee_map = {}

# --- Funções Auxiliares ---
def normalize_text(text):
    if pd.isna(text): return ""
    text = str(text).upper().strip()
    return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')

def find_best_match(requested_del, committee_code, available_dels):
    if not requested_del or committee_code not in available_dels: return None
    req_norm = normalize_text(requested_del)
    req_norm_clean = req_norm.split('-')[0].strip()
    available = available_dels[committee_code]
    avail_norm = [normalize_text(d) for d in available]
    
    for idx, an in enumerate(avail_norm):
        if an == req_norm: return available[idx]
    for idx, an in enumerate(avail_norm):
        if req_norm in an or an in req_norm: return available[idx]
        if req_norm_clean and (req_norm_clean in an or an in req_norm_clean): return available[idx]
            
    matches = difflib.get_close_matches(req_norm, avail_norm, n=1, cutoff=0.6)
    if matches: return available[avail_norm.index(matches[0])]
    return None

def extrair_dados_pessoais(row):
    """Busca dinamicamente colunas de contato na linha do forms"""
    if row is None: return {'E-mail': '', 'Celular': '', 'Instituição': ''}
    
    email = next((row[c] for c in row.keys() if 'mail' in str(c).lower() and not pd.isna(row[c])), "")
    celular = next((row[c] for c in row.keys() if ('celular' in str(c).lower() or 'telefone' in str(c).lower()) and not pd.isna(row[c])), "")
    instituicao = next((row[c] for c in row.keys() if ('instituição' in str(c).lower() or 'unidade' in str(c).lower() or 'escola' in str(c).lower()) and not pd.isna(row[c])), "")
    
    return {'E-mail': email, 'Celular': celular, 'Instituição': instituicao}

# =====================================================================
# FASE 1: SETUP (Upload e Mapeamento)
# =====================================================================
if st.session_state.status == 'setup':
    st.title("🌍 Alocador Interativo - Setup")
    
    st.header("📂 1. Arquivos Base")
    col1, col2 = st.columns(2)
    with col1:
        del_file = st.file_uploader("Upload das Vagas (Excel)", type=['xlsx'])
    with col2:
        insc_files = st.file_uploader("Upload das Inscrições (Forms)", type=['xlsx'], accept_multiple_files=True)

    st.header("🔄 2. Continuar de Onde Parou? (Opcional)")
    st.info("Se você já rodou o sistema antes e baixou uma planilha de alocação, faça o upload do CSV dela aqui para continuar de onde parou.")
    prev_alloc_file = st.file_uploader("Upload da Planilha de Alocação Anterior (CSV)", type=['csv'])

    if del_file and insc_files:
        # Lê Delegações
        delegacoes_df = pd.read_excel(del_file)
        available_dels_temp = {}
        for col in delegacoes_df.columns:
            dels = delegacoes_df[col].dropna().astype(str).str.strip().tolist()
            available_dels_temp[normalize_text(col)] = [d.strip() for d in dels if d.strip()]

# Lê Inscrições (Busca Ultra Resiliente)
        dfs = []
        for f in insc_files:
            df = pd.read_excel(f)
            df.columns = df.columns.astype(str).str.strip()
            
            # Função interna para "caçar" a coluna de tempo não importa como esteja escrita
            def achar_coluna_tempo(colunas):
                for c in colunas:
                    c_lower = str(c).lower()
                    if 'carimbo' in c_lower or 'timestamp' in c_lower or 'data/hora' in c_lower or 'data e hora' in c_lower:
                        return c
                return None
                
            col_tempo = achar_coluna_tempo(df.columns)
            
            # Se não achou na primeira linha, pula as 3 linhas de legenda e tenta de novo
            if not col_tempo:
                df = pd.read_excel(f, skiprows=3)
                df.columns = df.columns.astype(str).str.strip()
                col_tempo = achar_coluna_tempo(df.columns)
                
            # Se achou, padroniza o nome para o resto do código funcionar
            if col_tempo:
                df.rename(columns={col_tempo: 'Carimbo de data/hora'}, inplace=True)
            else:
                # Se realmente não existir, ele avisa você na tela em vez de quebrar o site
                st.error(f"Erro: Não encontrei a coluna de Data/Hora no arquivo {f.name}. Verifique a planilha.")
                st.stop()
                
            dfs.append(df)
        
        insc_df = pd.concat(dfs, ignore_index=True).sort_values(by='Carimbo de data/hora').reset_index(drop=True)
        st.session_state.inscricoes_df = insc_df

        st.divider()

        # Mapeamento
        st.header("🔗 3. Mapeamento de Comitês")
        comites_form = set()
        for i in range(1, 6):
            if f'{i}ª opção de comitê:' in insc_df.columns:
                comites_form.update(insc_df[f'{i}ª opção de comitê:'].dropna().unique())
        
        opcoes_vagas = ["-- Ignorar --"] + delegacoes_df.columns.tolist()
        map_cols = st.columns(2)
        committee_map = {}
        for i, comite in enumerate(sorted([str(c) for c in comites_form if str(c).strip()])):
            with map_cols[i % 2]:
                escolha = st.selectbox(f"Forms: **{comite}**", opcoes_vagas, key=f"map_{comite}")
                if escolha != "-- Ignorar --":
                    committee_map[normalize_text(comite)] = normalize_text(escolha)

        st.divider()

        st.header("🌟 4. Delegados Estrela")
        todos_nomes = insc_df['Nome completo:'].dropna().unique().tolist()
        estrelas = st.multiselect("Selecione os VIPs (Eles furam a fila):", todos_nomes)
        config_estrelas = {}
        if estrelas:
            cols_star = st.columns(3)
            for i, nome in enumerate(estrelas):
                with cols_star[i % 3]:
                    config_estrelas[nome] = st.selectbox(f"Opção para {nome}:", [1, 2, 3, 4, 5], key=f"opt_{nome}")

        if st.button("🚀 Iniciar Alocação", type="primary", use_container_width=True):
            st.session_state.committee_map = committee_map
            st.session_state.available_delegations = available_dels_temp
            
            # --- PROCESSAR ALOCAÇÃO ANTERIOR (SE EXISTIR) ---
            if prev_alloc_file:
                try:
                    prev_df = pd.read_csv(prev_alloc_file)
                    if all(col in prev_df.columns for col in ['Nome', 'Comitê', 'Delegação']):
                        for _, row in prev_df.iterrows():
                            comite = str(row['Comitê'])
                            delegacao = str(row['Delegação'])
                            nome = str(row['Nome'])
                            
                            if comite != 'NÃO ALOCADO' and delegacao != 'NÃO ALOCADO':
                                st.session_state.allocated.append(row.to_dict())
                                st.session_state.pre_allocated_names.add(nome)
                                
                                comite_key = normalize_text(comite)
                                if comite_key in st.session_state.available_delegations:
                                    match = find_best_match(delegacao, comite_key, st.session_state.available_delegations)
                                    if match:
                                        st.session_state.available_delegations[comite_key].remove(match)
                except Exception as e:
                    st.error(f"Erro ao ler arquivo anterior: {e}")

            # --- PROCESSAR ESTRELAS NOVAS ---
            for nome in estrelas:
                if nome in st.session_state.pre_allocated_names:
                    continue
                    
                p_row = insc_df[insc_df['Nome completo:'] == nome].iloc[0]
                op = config_estrelas[nome]
                c_col = f'{op}ª opção de comitê:'
                d_col = f'{op}ª opção de delegação:'
                
                if not pd.isna(p_row.get(c_col)) and not pd.isna(p_row.get(d_col)):
                    c_code = committee_map.get(normalize_text(p_row[c_col]), None)
                    if c_code:
                        match = find_best_match(p_row[d_col], c_code, st.session_state.available_delegations)
                        if match:
                            dados = {
                                'Timestamp': p_row['Carimbo de data/hora'], 'Nome': nome,
                                'Comitê': c_code.upper(), 'Delegação': match, 'Opção': f"{op} (VIP)",
                                'Dupla': p_row.get('Nome completo da dupla (se houver):', "")
                            }
                            dados.update(extrair_dados_pessoais(p_row)) # Adiciona contato
                            st.session_state.allocated.append(dados)
                            
                            st.session_state.available_delegations[c_code].remove(match)
                            st.session_state.pre_allocated_names.add(nome)

            st.session_state.status = 'processing'
            st.rerun()

# =====================================================================
# FASE 2: PROCESSAMENTO AUTOMÁTICO
# =====================================================================
if st.session_state.status == 'processing':
    df = st.session_state.inscricoes_df
    mapa = st.session_state.committee_map
    vagas = st.session_state.available_delegations
    
    while st.session_state.current_idx < len(df):
        row = df.iloc[st.session_state.current_idx]
        name = row.get('Nome completo:', np.nan)
        
        if pd.isna(name) or name in st.session_state.pre_allocated_names:
            st.session_state.current_idx += 1
            continue
            
        alocado = False
        for i in range(1, 6):
            c_col = f'{i}ª opção de comitê:'
            d_col = f'{i}ª opção de delegação:'
            if c_col not in row or d_col not in row: continue
            if pd.isna(row[c_col]) or pd.isna(row[d_col]): continue
                
            c_code = mapa.get(normalize_text(row[c_col]), None)
            if not c_code: continue
                
            match = find_best_match(row[d_col], c_code, vagas)
            if match:
                dados = {
                    'Timestamp': row['Carimbo de data/hora'], 'Nome': name,
                    'Comitê': c_code.upper(), 'Delegação': match, 'Opção': i,
                    'Dupla': row.get('Nome completo da dupla (se houver):', "")
                }
                dados.update(extrair_dados_pessoais(row)) # Adiciona contato
                st.session_state.allocated.append(dados)
                
                vagas[c_code].remove(match)
                alocado = True
                st.session_state.current_idx += 1
                break
                
        if not alocado:
            st.session_state.person_to_resolve = row
            st.session_state.status = 'resolving'
            st.rerun()
            break
            
    if st.session_state.current_idx >= len(df):
        st.session_state.status = 'finished'
        st.rerun()

# =====================================================================
# FASE 3: RESOLUÇÃO MANUAL
# =====================================================================
if st.session_state.status == 'resolving':
    row = st.session_state.person_to_resolve
    nome = row.get('Nome completo:', 'Desconhecido')
    
    st.error(f"⚠️ PROCESSO PAUSADO: {nome} não conseguiu vaga!")
    
    # Busca dados pessoais usando a nova função
    dados_pessoais = extrair_dados_pessoais(row)
    
    st.subheader(f"👤 Dados de {nome}")
    col_info1, col_info2 = st.columns(2)
    
    col_info1.write(f"**E-mail:** {dados_pessoais['E-mail'] or 'Não informado'}")
    col_info2.write(f"**Celular:** {dados_pessoais['Celular'] or 'Não informado'}")
    
    col_info1.write(f"**Instituição:** {dados_pessoais['Instituição'] or 'Não informado'}")
    if not pd.isna(row.get('Nome completo da dupla (se houver):')):
        col_info2.write(f"**Dupla:** {row['Nome completo da dupla (se houver):']}")

    st.write("**Opções Originais (Frustradas):**")
    for i in range(1, 6):
        c_col = row.get(f'{i}ª opção de comitê:', '')
        d_col = row.get(f'{i}ª opção de delegação:', '')
        if not pd.isna(c_col) and not pd.isna(d_col):
            st.caption(f"{i}ª: {c_col} - {d_col}")

    st.divider()

    col_vagas, col_acao = st.columns([2, 1])
    
    with col_vagas:
        st.subheader("📋 Vagas Disponíveis")
        vagas_atuais = st.session_state.available_delegations
        max_len = max([len(v) for v in vagas_atuais.values()]) if vagas_atuais else 0
        df_vagas = pd.DataFrame({k: v + [""]*(max_len - len(v)) for k, v in vagas_atuais.items()})
        st.dataframe(df_vagas, use_container_width=True, height=300)

    with col_acao:
        st.subheader("🛠️ Ação Manual")
        comite_escolhido = st.selectbox("Escolha um Comitê:", list(vagas_atuais.keys()))
        
        opcoes_del = vagas_atuais.get(comite_escolhido, [])
        if opcoes_del:
            del_escolhida = st.selectbox("Escolha a Delegação:", opcoes_del)
            if st.button("✅ Confirmar Alocação", type="primary", use_container_width=True):
                dados = {
                    'Timestamp': row['Carimbo de data/hora'], 'Nome': nome,
                    'Comitê': comite_escolhido.upper(), 'Delegação': del_escolhida, 'Opção': "MANUAL",
                    'Dupla': row.get('Nome completo da dupla (se houver):', "")
                }
                dados.update(dados_pessoais) # Adiciona contato
                st.session_state.allocated.append(dados)
                
                st.session_state.available_delegations[comite_escolhido].remove(del_escolhida)
                st.session_state.current_idx += 1
                st.session_state.status = 'processing'
                st.rerun()
        else:
            st.warning("Comitê cheio!")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⏭️ Pular / Deixar sem vaga", use_container_width=True):
            dados = {
                'Timestamp': row['Carimbo de data/hora'], 'Nome': nome,
                'Comitê': "NÃO ALOCADO", 'Delegação': "NÃO ALOCADO", 'Opção': "N/A",
                'Dupla': row.get('Nome completo da dupla (se houver):', "")
            }
            dados.update(dados_pessoais) # Adiciona contato
            st.session_state.allocated.append(dados)
            
            st.session_state.current_idx += 1
            st.session_state.status = 'processing'
            st.rerun()

    with st.expander("Ver lista de quem já foi alocado até agora"):
        st.dataframe(pd.DataFrame(st.session_state.allocated))

# =====================================================================
# FASE 4: FINALIZAÇÃO
# =====================================================================
if st.session_state.status == 'finished':
    st.balloons()
    st.title("🎉 Alocação Concluída!")
    
    df_final = pd.DataFrame(st.session_state.allocated)
    
    tab_aloc, tab_nao = st.tabs(["✅ Alocados", "⚠️ Sem Vaga"])
    with tab_aloc: st.dataframe(df_final[df_final['Comitê'] != 'NÃO ALOCADO'], use_container_width=True)
    with tab_nao: st.dataframe(df_final[df_final['Comitê'] == 'NÃO ALOCADO'], use_container_width=True)

    colA, colB = st.columns(2)
    with colA:
        csv = df_final.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button("📥 Baixar Planilha Final (CSV)", data=csv, file_name='alocacao_final.csv', mime='text/csv', type="primary")
    with colB:
        if st.button("🔄 Novo Processo"):
            for key in st.session_state.keys(): del st.session_state[key]
            st.rerun()

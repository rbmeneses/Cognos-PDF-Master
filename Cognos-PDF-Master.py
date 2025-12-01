import streamlit as st
import io
import zipfile
import os 
import tempfile 
from typing import List
import fitz  # PyMuPDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from docx import Document
from pdf2docx import Converter # ### NOVO: Necessário pip install pdf2docx

# --- Configuração da Página e CSS ---
st.set_page_config(
    page_title="Cognos PDF Master",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CSS aprimorado
st.markdown("""
<style>
    .card {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 12px;
        text-align: center;
        transition: all 0.3s ease;
        cursor: pointer;
        border: 1px solid #e0e0e0;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .card:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 15px rgba(0,0,0,0.1);
        border-color: #4b7bff;
    }
    .card-icon { font-size: 40px; margin-bottom: 15px; }
    .card-title { font-weight: bold; font-size: 18px; color: #31333F; margin-bottom: 5px; }
    .card-desc { font-size: 13px; color: #666; line-height: 1.4; }
    
    .stButton button { width: 100%; border-radius: 8px; }
    
    /* Estilo para o container de preview */
    .preview-box {
        border: 2px dashed #ccc;
        padding: 10px;
        border-radius: 10px;
        background-color: #f9f9f9;
        text-align: center;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# --- Lógica de Negócio (Service Layer) ---
class PDFEngine:
    """Motor de processamento de PDFs utilizando PyMuPDF e ReportLab."""

    @staticmethod
    def get_preview_image(file_stream, page_num=0, dpi=100) -> bytes:
        """Gera bytes de imagem PNG de uma página específica do PDF para preview."""
        try:
            # Verifica se é BytesIO ou arquivo aberto
            stream_data = file_stream.read() if hasattr(file_stream, 'read') else file_stream
            if hasattr(file_stream, 'seek'): file_stream.seek(0)

            with fitz.open(stream=stream_data, filetype="pdf") as doc:
                if page_num < len(doc):
                    page = doc[page_num]
                    pix = page.get_pixmap(dpi=dpi)
                    return pix.tobytes("png"), len(doc)
            
            if hasattr(file_stream, 'seek'): file_stream.seek(0)
        except Exception:
            return None, 0
        return None, 0

    @staticmethod
    def merge_pdfs(files: List) -> bytes:
        doc_merged = fitz.open()
        for file in files:
            with fitz.open(stream=file.read(), filetype="pdf") as doc:
                doc_merged.insert_pdf(doc)
        output_buffer = io.BytesIO()
        doc_merged.save(output_buffer)
        doc_merged.close()
        return output_buffer.getvalue()

    @staticmethod
    def split_pdf(file, ranges: str) -> bytes:
        with fitz.open(stream=file.read(), filetype="pdf") as doc:
            doc_new = fitz.open()
            page_numbers = set()
            parts = ranges.split(',')
            for part in parts:
                part = part.strip()
                if '-' in part:
                    try:
                        start, end = map(int, part.split('-'))
                        page_numbers.update(range(start - 1, end))
                    except ValueError:
                        continue
                else:
                    try:
                        page_numbers.add(int(part) - 1)
                    except ValueError:
                        continue

            sorted_pages = sorted([p for p in page_numbers if 0 <= p < len(doc)])
            if not sorted_pages:
                raise ValueError("Nenhuma página válida selecionada.")

            for page_num in sorted_pages:
                doc_new.insert_pdf(doc, from_page=page_num, to_page=page_num)

            output_buffer = io.BytesIO()
            doc_new.save(output_buffer)
            doc_new.close()
            return output_buffer.getvalue()

    @staticmethod
    def compress_pdf(file) -> bytes:
        with fitz.open(stream=file.read(), filetype="pdf") as doc:
            output_buffer = io.BytesIO()
            doc.save(output_buffer, garbage=4, deflate=True) 
            return output_buffer.getvalue()

    @staticmethod
    def rotate_pdf(file, rotation_angle: int) -> bytes:
        with fitz.open(stream=file.read(), filetype="pdf") as doc:
            for page in doc:
                page.set_rotation(rotation_angle)
            output_buffer = io.BytesIO()
            doc.save(output_buffer)
            return output_buffer.getvalue()

    @staticmethod
    def protect_pdf(file, password: str) -> bytes:
        with fitz.open(stream=file.read(), filetype="pdf") as doc:
            output_buffer = io.BytesIO()
            doc.save(output_buffer, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=password, user_pw=password)
            return output_buffer.getvalue()

    @staticmethod
    def sign_pdf(pdf_file, img_file, page_num: int, x: int, y: int, width: int) -> bytes:
        pdf_bytes = pdf_file.read() if hasattr(pdf_file, 'read') else pdf_file
        img_bytes = img_file.read() if hasattr(img_file, 'read') else img_file
        
        if hasattr(pdf_file, 'seek'): pdf_file.seek(0)
        if hasattr(img_file, 'seek'): img_file.seek(0)

        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if page_num < 1 or page_num > len(doc):
                raise ValueError("Número de página inválido.")
            
            page = doc[page_num - 1]
            
            with fitz.open(stream=img_bytes) as img_temp:
                pix = img_temp[0].get_pixmap()
                aspect_ratio = pix.height / pix.width
                
            height = width * aspect_ratio
            rect = fitz.Rect(x, y, x + width, y + height)
            
            page.insert_image(rect, stream=img_bytes)
            
            output_buffer = io.BytesIO()
            doc.save(output_buffer)
            return output_buffer.getvalue()

    @staticmethod
    def extract_text(file) -> bytes:
        text_out = ""
        with fitz.open(stream=file.read(), filetype="pdf") as doc:
            for page in doc:
                text_out += page.get_text() + "\n\n"
        return text_out.encode('utf-8')

    @staticmethod
    def pdf_to_jpg(file) -> bytes:
        with fitz.open(stream=file.read(), filetype="pdf") as doc:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, page in enumerate(doc):
                    pix = page.get_pixmap(dpi=150)
                    img_data = pix.tobytes("jpg")
                    zf.writestr(f"pagina_{i+1}.jpg", img_data)
            return zip_buffer.getvalue()

    @staticmethod
    def jpg_to_pdf(image_files: List) -> bytes:
        doc = fitz.open()
        for img_file in image_files:
            img_bytes = img_file.read()
            img_file.seek(0)
            with fitz.open(stream=img_bytes) as img_doc:
                pdfbytes = img_doc.convert_to_pdf()
                with fitz.open("pdf", pdfbytes) as pdf_page:
                    doc.insert_pdf(pdf_page)
        output_buffer = io.BytesIO()
        doc.save(output_buffer)
        doc.close()
        return output_buffer.getvalue()

    @staticmethod
    def office_to_pdf(file) -> bytes:
        filename = file.name.lower()
        text_content = []
        if filename.endswith('.docx'):
            doc = Document(file)
            for para in doc.paragraphs:
                if para.text: text_content.append(para.text)
        elif filename.endswith('.txt'):
            text_content = file.read().decode("utf-8").split('\n')

        output_buffer = io.BytesIO()
        doc_template = SimpleDocTemplate(output_buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = [Paragraph(line, styles["Normal"]) for line in text_content if line.strip()]
        story = [x for item in story for x in (item, Spacer(1, 10))]
        doc_template.build(story)
        return output_buffer.getvalue()

    # ### NOVO: Função para PDF -> DOCX ###
    @staticmethod
    def pdf_to_docx(file) -> bytes:
        """Converte PDF para DOCX usando pdf2docx com arquivos temporários."""
        # Cria arquivos temporários pois a lib pdf2docx trabalha melhor com caminhos de arquivo
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
            tmp_pdf.write(file.read())
            tmp_pdf_path = tmp_pdf.name

        docx_path = tmp_pdf_path.replace(".pdf", ".docx")

        try:
            cv = Converter(tmp_pdf_path)
            cv.convert(docx_path)
            cv.close()

            with open(docx_path, "rb") as f:
                docx_bytes = f.read()
        finally:
            # Limpeza dos arquivos temporários
            if os.path.exists(tmp_pdf_path): os.remove(tmp_pdf_path)
            if os.path.exists(docx_path): os.remove(docx_path)
            
        return docx_bytes

# --- Helpers de UI ---
def ui_show_pdf_preview(file, label="Preview (Pág. 1)", expanded=True):
    """Componente reutilizável para mostrar preview"""
    with st.expander(label, expanded=expanded):
        img_data, count = PDFEngine.get_preview_image(file)
        if img_data:
            st.image(img_data, caption=f"Página 1 de {count}", use_container_width=True)
        else:
            st.warning("Não foi possível gerar preview deste arquivo.")

def navigate_to(tool_name):
    st.session_state['active_tool'] = tool_name

def render_home():
    st.title("Cognos PDF Master")
    st.markdown("### Selecione uma ferramenta")
    st.markdown("### ☕ Apoie o Projeto (PIX) 21980892973")
    st.markdown("<br>", unsafe_allow_html=True)

    tools = [
        {"id": "merge", "icon": "🔗", "title": "Juntar PDF", "desc": "Combine arquivos."},
        {"id": "split", "icon": "✂️", "title": "Dividir PDF", "desc": "Extraia páginas."},
        {"id": "sign", "icon": "✍️", "title": "Assinar PDF", "desc": "Insira assinatura."},
        {"id": "compress", "icon": "🗜️", "title": "Comprimir", "desc": "Reduza o tamanho."},
        {"id": "protect", "icon": "🔒", "title": "Proteger", "desc": "Adicione senha."},
        {"id": "rotate", "icon": "🔄", "title": "Rotacionar", "desc": "Gire as páginas."},
        {"id": "extract_text", "icon": "📝", "title": "Extrair Texto", "desc": "PDF para TXT."},
        {"id": "pdf_jpg", "icon": "🖼️", "title": "PDF p/ JPG", "desc": "Converta em imagens."},
        {"id": "jpg_pdf", "icon": "📷", "title": "JPG p/ PDF", "desc": "Imagens em PDF."},
        {"id": "office_pdf", "icon": "📄", "title": "Word p/ PDF", "desc": "DOCX simples p/ PDF."},
        # ### NOVO: Card adicionado ###
        {"id": "pdf_docx", "icon": "📘", "title": "PDF p/ Word", "desc": "Converta para DOCX."} 
    ]

    cols = st.columns(4)
    for i, tool in enumerate(tools):
        with cols[i % 4]:
            st.markdown(f"""
            <div class="card">
                <div class="card-icon">{tool['icon']}</div>
                <div class="card-title">{tool['title']}</div>
                <div class="card-desc">{tool['desc']}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Abrir", key=tool['id'], use_container_width=True):
                navigate_to(tool['id'])
            st.markdown("<br>", unsafe_allow_html=True)

def render_tool_page():
    tool = st.session_state.get('active_tool')

    col1, col2 = st.columns([1, 6])
    with col1:
        if st.button("⬅️ Voltar"):
            navigate_to("home")
            st.rerun()
    with col2:
        st.subheader(f"Ferramenta: {tool.replace('_', ' ').upper()}")
        st.markdown("---")

    try:
        # --- JUNTAR ---
        if tool == "merge":
            files = st.file_uploader("Selecione PDFs", type="pdf", accept_multiple_files=True)
            if files:
                st.info(f"{len(files)} arquivos selecionados.")
                with st.expander("👁️ Ver Previews dos Arquivos"):
                    cols_prev = st.columns(3)
                    for idx, f in enumerate(files):
                        with cols_prev[idx % 3]:
                            ui_show_pdf_preview(f, label=f.name, expanded=True)
            
            if files and st.button("Juntar PDFs", type="primary"):
                with st.spinner("Processando..."):
                    res = PDFEngine.merge_pdfs(files)
                    st.success("Concluído!")
                    st.download_button("Baixar PDF Unido", res, "merged.pdf", "application/pdf")

        # --- DIVIDIR ---
        elif tool == "split":
            file = st.file_uploader("Selecione PDF", type="pdf")
            if file:
                ui_show_pdf_preview(file, "👁️ Preview do Documento")
                
            ranges = st.text_input("Intervalo (ex: 1-5, 8)", help="Use hífen para intervalos e vírgula para páginas soltas.")
            if file and ranges and st.button("Dividir PDF", type="primary"):
                res = PDFEngine.split_pdf(file, ranges)
                st.success("Concluído!")
                st.download_button("Baixar PDF Dividido", res, "split.pdf", "application/pdf")

        # --- ASSINAR ---
        elif tool == "sign":
            col_pdf, col_img = st.columns(2)
            with col_pdf:
                file = st.file_uploader("1. Arquivo PDF", type="pdf")
            with col_img:
                img_sign = st.file_uploader("2. Imagem (PNG/JPG)", type=["png", "jpg", "jpeg"])
            
            if file and img_sign:
                st.write("Configurações da Assinatura:")
                c1, c2, c3, c4 = st.columns(4)
                with c1: page_num = st.number_input("Página", min_value=1, value=1)
                with c2: width = st.slider("Largura", 50, 500, 150)
                with c3: x_pos = st.slider("Posição X", 0, 600, 100)
                with c4: y_pos = st.slider("Posição Y", 0, 800, 500)
                
                if st.button("👁️ Testar Posição (Gerar Preview)"):
                     try:
                        temp_pdf = PDFEngine.sign_pdf(file, img_sign, page_num, x_pos, y_pos, width)
                        with fitz.open(stream=temp_pdf, filetype="pdf") as doc:
                            page = doc[page_num - 1]
                            pix = page.get_pixmap(dpi=100)
                            st.image(pix.tobytes("png"), caption="Simulação da Assinatura", use_container_width=True)
                     except Exception as e:
                         st.error(f"Erro no preview: {e}")

                if st.button("Aplicar Assinatura Definitiva", type="primary"):
                    res = PDFEngine.sign_pdf(file, img_sign, page_num, x_pos, y_pos, width)
                    st.success("Assinado!")
                    st.download_button("Baixar PDF Assinado", res, "signed.pdf", "application/pdf")

        # --- PROTEGER ---
        elif tool == "protect":
            file = st.file_uploader("Selecione PDF", type="pdf")
            if file: ui_show_pdf_preview(file)
            password = st.text_input("Defina uma senha", type="password")
            if file and password and st.button("Proteger PDF", type="primary"):
                res = PDFEngine.protect_pdf(file, password)
                st.success("Protegido!")
                st.download_button("Baixar PDF Protegido", res, "protected.pdf", "application/pdf")

        # --- ROTACIONAR ---
        elif tool == "rotate":
            file = st.file_uploader("Selecione PDF", type="pdf")
            if file: ui_show_pdf_preview(file, label="Estado Atual")
            angle = st.select_slider("Ângulo de Rotação", options=[90, 180, 270])
            if file and st.button("Rotacionar", type="primary"):
                res = PDFEngine.rotate_pdf(file, angle)
                st.success("Rotacionado!")
                with st.expander("Resultado"):
                     img_res, _ = PDFEngine.get_preview_image(io.BytesIO(res))
                     st.image(img_res, caption="Como ficou", use_container_width=True)
                st.download_button("Baixar PDF Rotacionado", res, "rotated.pdf", "application/pdf")

        # --- EXTRAIR TEXTO ---
        elif tool == "extract_text":
            file = st.file_uploader("Selecione PDF", type="pdf")
            if file: ui_show_pdf_preview(file)
            if file and st.button("Extrair Texto", type="primary"):
                res = PDFEngine.extract_text(file)
                st.success("Extraído!")
                st.text_area("Preview Texto", res.decode('utf-8')[:1000] + "...", height=200)
                st.download_button("Baixar Texto (.txt)", res, "conteudo.txt", "text/plain")

        # --- COMPRIMIR ---
        elif tool == "compress":
            file = st.file_uploader("Selecione PDF", type="pdf")
            if file: ui_show_pdf_preview(file)
            if file and st.button("Comprimir PDF", type="primary"):
                res = PDFEngine.compress_pdf(file)
                st.success(f"Redução de {(1 - (len(res) / file.size)) * 100:.1f}%")
                st.download_button("Baixar Otimizado", res, "compressed.pdf", "application/pdf")

        # --- PDF PARA JPG ---
        elif tool == "pdf_jpg":
            file = st.file_uploader("Selecione PDF", type="pdf")
            if file: ui_show_pdf_preview(file)
            if file and st.button("Converter", type="primary"):
                res = PDFEngine.pdf_to_jpg(file)
                st.download_button("Baixar ZIP", res, "imagens.zip", "application/zip")

        # --- JPG PARA PDF ---
        elif tool == "jpg_pdf":
            files = st.file_uploader("Selecione Imagens", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
            if files:
                st.image(files, width=150, caption=[f.name for f in files])
            if files and st.button("Gerar PDF", type="primary"):
                res = PDFEngine.jpg_to_pdf(files)
                st.success("Gerado!")
                img_res, _ = PDFEngine.get_preview_image(io.BytesIO(res))
                st.image(img_res, caption="PDF Gerado", width=300)
                st.download_button("Baixar PDF", res, "photos.pdf", "application/pdf")

        # --- OFFICE PARA PDF ---
        elif tool == "office_pdf":
            file = st.file_uploader("DOCX ou TXT", type=["docx", "txt"])
            if file and st.button("Converter", type="primary"):
                res = PDFEngine.office_to_pdf(file)
                st.success("Convertido!")
                ui_show_pdf_preview(io.BytesIO(res), "Como ficou o PDF")
                st.download_button("Baixar PDF", res, "doc.pdf", "application/pdf")
        
        # ### NOVO: Lógica da Interface PDF -> DOCX ###
        elif tool == "pdf_docx":
            file = st.file_uploader("Selecione PDF", type="pdf")
            if file: ui_show_pdf_preview(file)
            if file and st.button("Converter para Word", type="primary"):
                with st.spinner("Convertendo... (Isso pode levar alguns segundos)"):
                    res = PDFEngine.pdf_to_docx(file)
                    st.success("Convertido com sucesso!")
                    st.download_button(
                        label="Baixar Arquivo Word (.docx)",
                        data=res,
                        file_name="convertido.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )

    except Exception as e:
        st.error(f"Erro: {str(e)}")

def main():
    if 'active_tool' not in st.session_state:
        st.session_state['active_tool'] = 'home'
    if st.session_state['active_tool'] == 'home':
        render_home()
    else:
        render_tool_page()

if __name__ == "__main__":

    main()




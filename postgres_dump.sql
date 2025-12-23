--
-- PostgreSQL database dump
--

\restrict cQHhn31VKBeOjvfonqCgJTAbIBf4g6I8uwhrB15R79Sz4qltemDjgcrGUzizdqv

-- Dumped from database version 14.20 (Homebrew)
-- Dumped by pg_dump version 14.20 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: categories; Type: TABLE; Schema: public; Owner: pro100kir2
--

CREATE TABLE public.categories (
    id integer NOT NULL,
    name text
);


ALTER TABLE public.categories OWNER TO pro100kir2;

--
-- Name: categories_id_seq; Type: SEQUENCE; Schema: public; Owner: pro100kir2
--

CREATE SEQUENCE public.categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.categories_id_seq OWNER TO pro100kir2;

--
-- Name: categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pro100kir2
--

ALTER SEQUENCE public.categories_id_seq OWNED BY public.categories.id;


--
-- Name: gigachat_token; Type: TABLE; Schema: public; Owner: pro100kir2
--

CREATE TABLE public.gigachat_token (
    id integer NOT NULL,
    access_token text NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.gigachat_token OWNER TO pro100kir2;

--
-- Name: gigachat_token_id_seq; Type: SEQUENCE; Schema: public; Owner: pro100kir2
--

CREATE SEQUENCE public.gigachat_token_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.gigachat_token_id_seq OWNER TO pro100kir2;

--
-- Name: gigachat_token_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pro100kir2
--

ALTER SEQUENCE public.gigachat_token_id_seq OWNED BY public.gigachat_token.id;


--
-- Name: products; Type: TABLE; Schema: public; Owner: pro100kir2
--

CREATE TABLE public.products (
    id integer NOT NULL,
    title text NOT NULL,
    category_id integer,
    avito_url text NOT NULL,
    price integer,
    created_at timestamp without time zone DEFAULT now(),
    description text,
    image_url text,
    sizes text
);


ALTER TABLE public.products OWNER TO pro100kir2;

--
-- Name: products_id_seq; Type: SEQUENCE; Schema: public; Owner: pro100kir2
--

CREATE SEQUENCE public.products_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.products_id_seq OWNER TO pro100kir2;

--
-- Name: products_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pro100kir2
--

ALTER SEQUENCE public.products_id_seq OWNED BY public.products.id;


--
-- Name: categories id; Type: DEFAULT; Schema: public; Owner: pro100kir2
--

ALTER TABLE ONLY public.categories ALTER COLUMN id SET DEFAULT nextval('public.categories_id_seq'::regclass);


--
-- Name: gigachat_token id; Type: DEFAULT; Schema: public; Owner: pro100kir2
--

ALTER TABLE ONLY public.gigachat_token ALTER COLUMN id SET DEFAULT nextval('public.gigachat_token_id_seq'::regclass);


--
-- Name: products id; Type: DEFAULT; Schema: public; Owner: pro100kir2
--

ALTER TABLE ONLY public.products ALTER COLUMN id SET DEFAULT nextval('public.products_id_seq'::regclass);


--
-- Data for Name: categories; Type: TABLE DATA; Schema: public; Owner: pro100kir2
--

COPY public.categories (id, name) FROM stdin;
2	Мужская одежда
3	Женская одежда
4	Обувь и аксессуары
\.


--
-- Data for Name: gigachat_token; Type: TABLE DATA; Schema: public; Owner: pro100kir2
--

COPY public.gigachat_token (id, access_token, updated_at) FROM stdin;
14	eyJjdHkiOiJqd3QiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.w84k7okafjUxLkXUDqDUMeVkOISydbmSSmdqJRmB1gWQnt8rSlE47XA-k1dp5zdbS3Xyzm5fGKlcIMh-9SyKKGqmaW6mr4Q382KAVWQiilTlQslQ9QvFl1_wFLGk3oJzmv_NTbGCT2jtRyk_GRacP1MXPUED-OmEUsNAhZ_BWqD5HyySxPYKv9m16Upm5ZXpu2Wnj5klSCEEtt60iYLUoEeB97AgaG47Y3_NUPldghpK4Oc173UkA4GJ7UI_Yoa9DHMMFh_UUlTZSV2j67CivMnlzV99kVJ6OkXuHVL_hJqjRb1s77FNdSYavS9_6De-tWeAthBiEWnHH5hynCxFQw.-dlt5SVwytN1-LKYE0NKrw.uKv8v4BFo803hMRTNObcp9VMuPiZFvc3sLTO3WV7_XYNZuatync6Xpl-jUdvsacsN4eDxbTp9X7UJPPBxVDg9Z9HtkbXkTVb-wr6xgWYcosHH1OIblJTAoTB5F3jpPZJn4eRkFBBfSTGOfPi0Q68WO8cvukSVy-gHadfv0ZeeLhJlCTOQay1BLbo30GGscloY9-7ypyds9auQvUzRaQKRs__pzw5Ffk7x1_AIePSqmYROHt8XVX0Hv5v2CW16eJIc5EMbdedNRRnjqR9Y5t87i5jZ0YJR0mW_BOfsv3ZLE8dQDpILJMbnsBx3m84ajHD9w9d2wNHloqXpnbMxqwx7MzL63yApKgu4imqaZn4Sic4JZMkpcSK_1FQZkr_0e5jns5wR4wLjEcvCNes1Dwg5ePSuLhnWjFoAXrMTXr_82ZzrcMW9eUd36XZonap3Ox-9jIfwWsMJ6MKLb5Y6PPKxr90JVNSBfUR5Fjdf3J4pSrmFFzsTZqqD9EE2ZNLOfreOWgNB49Tour0DJytn6-frAwbMxglsDvYm_lgKQ-lQHoxY9S-t8ZoFLMQA8i51u5QFSoGNUvGlodtY_K33ZMb-CfcBLvT7KHaGq3yTwdatLr_rlUY2TUZqV0t6Ku71pci6A78Ps0NqdfvPOXuC9Mi6oZBooRHbNtN-_BGBIl1Tlj5T6sZSa3dlgOuvmxrJXvh0yfQCzkFrhtM3STDLJxqcsAji4F7uF0Ck82Yx0UnYIU.evRR5Z9uM5-euQD-gk3z1Zt_iRtBikzCPTZfvOMBDKU	2025-12-23 06:24:58.653102
\.


--
-- Data for Name: products; Type: TABLE DATA; Schema: public; Owner: pro100kir2
--

COPY public.products (id, title, category_id, avito_url, price, created_at, description, image_url, sizes) FROM stdin;
1	Мужские брюки Eleventy	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/muzhskie_bryuki_eleventy36_7766627394?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	13000	2025-12-22 23:20:41.368251	Мужские брюки Eleventy, размер 36.\nЦвет синий. Новые, с бирками. Повседневный стиль.	https://30.img.avito.st/image/1/1.hJ0pnraAKHQ_Pop1LbyZxXc_KnCbKSx0m05JcJudKdacPSxuPz6KdZ8.RIywU31DHSpHFebVFkWdXf-WMTeDUUTeOUCahky2CYg?cqp=2.31EmCLg6ik3oatt1ttbFq_ajuGsz9wCshVqsaNgtLVVqtiwIcdxsWidTBGP4W2gjZpwuVqcdzwQCR5DnUbaoBbU1	36
2	Куртка Eleventy из материалов Loro Piana	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/kurtka_eleventy_iz_materialov_loro_piana4850_7702041160?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	24750	2025-12-22 23:20:43.150294	Куртка Eleventy из серии Platinum. Компания использовала материалы от фабрики Loro Piana. Цвет светло синий. В размере 48,50.	https://20.img.avito.st/image/1/1.Jlkqs7aAirA8Eyixaq9EPHMSiLSYBI6wmGPrtJiwixKfEI6qPBMosZw.J1wepegayv4AhRERUqDoNyUIEhv8H8dGTQcdLPsP7JQ?cqp=2.31EmCLg6ik3oatt1ttbFq_ajuGsz9wCshVqsaNgtLVVqtiwIcdxsWidTBGP4W2gjZpwuVqcdzwQCR5DnUbaoBbU1	48,50
4	Костюм мужской Eleventy (шерсть 100%)	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/kostyum_muzhskoy_eleventy_sherst_100_5054_7798741995?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	34000	2025-12-22 23:20:46.43611	Продается мужской костюм Eleventy из шерсти,\nразмеры в наличии: 50,54.	https://80.img.avito.st/image/1/1.OFz8hraAlLXqJja0gPI2FaQnlrFOMZC1Tlb1sU6FlRdJJZCv6iY2tEo.JINTG6ebcXqg67foyQJIk3jybsqS9OzbCC9V-o-Qwqw	\N
3	Куртка Eleventy из материала Loro Piana	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/kurtka_eleventy_iz_materiala_loro_piana48_7702359099?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	21675	2025-12-22 23:20:44.898247	Оригинальная крутка Eleventy из линии Platinum. Материалы для этой модели использовали от Loro Piana, что символизирует о высоком качестве. В наличии размеры 48.	https://00.img.avito.st/image/1/1.NuXmP7aAmgzwnzgNhisjgb-emAhUiJ4MVO_7CFQ8m65TnJ4W8J84DVA.nIoh5n4b9rwlTAekSQvDrTbtNBVBZMkjfbXNWxb9N_I?cqp=2.31EmCLg6ik3oatt1ttbFq_ajuGsz9wCshVqsaNgtLVVqtiwIcdxsWidTBGP4W2gjZpwuVqcdzwQCR5DnUbaoBbU1	48
5	Спортивные брюки Eleventy из хлопка	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/sportivnye_bryuki_eleventy_iz_hlopka_xl_7798502365?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	15000	2025-12-22 23:20:48.141221	Спортивные брюки Eleventy из мягкого хлопка, размер XL. Универсальный серый цвет подходит к любому гардеробу. Эластичная резинка на поясе обеспечивает комфортную посадку, а плотная ткань сохраняет форму и долговечность. Новые, с бирками.	https://40.img.avito.st/image/1/1.O4B_k7aAl2lpMzVoBeMukSUylW3NJJNpzUP2bc2QlsvKMJNzaTM1aMk.RnKPeYpf4ZbAk4_Xefki3j1ctJJfqCS_FURNqJUcqHw	XL
6	Мужские Брюки Eleventy Milano	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/muzhskie_bryuki_eleventy_milano_30313238_7766799594?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	15000	2025-12-22 23:20:49.54431	Мужские брюки Eleventy из Италии, размер 30/31/32/38. Изготовлены из шерсти и эластана для комфорта и долговечности.	https://00.img.avito.st/image/1/1.L3DD7LaAg5nVTCGYkdAlKJ1NgZ1xW4eZcTzinXHvgjt2T4eD1UwhmHU.Jts9_RlvjCooSkH0LIitRwTV7kMcjdKcAOSv0t96s6Y?cqp=2.31EmCLg6ik3oatt1ttbFq_ajuGsz9wCshVqsaNgtLVVqtiwIcdxsWidTBGP4W2gjZpwuVqcdzwQCR5DnUbaoBbU1	30,31,32,38
7	Пиджак Eleventy из шерсти	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/pidzhak_eleventy_iz_shersti_4850_7862245930?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	36000	2025-12-22 23:20:51.378202	Пиджак Eleventy из шерсти, размеры — 48,50,52,54, насыщенного синего цвета. Новый, с бирками. Капюшон отстегивается.	https://20.img.avito.st/image/1/1.aRbLFbaAxf_dtWf-lSxZbYy0x_t5osH_ecWk-3kWxF1-tsHl3bVn_n0.AijZMyrksttBmTBF50b2txMF9I0STEhvlAS6WPPDtwU?cqp=2.31EmCLg6ik3oatt1ttbFq_ajuGsz9wCshVqsaNgtLVVqtiwIcdxsWidTBGP4W2gjZpwuVqcdzwQCR5DnUbaoBbU1	48,50
8	Брюки Eleventy из шерсти и кашемира	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/bryuki_eleventy_iz_shersti_i_kashemira_31_7798541012?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	13500	2025-12-22 23:20:52.730703	Новые брюки Eleventy из шерсти и кашемира серого цвета. Размер 31. Подходят для классического стиля.	https://50.img.avito.st/image/1/1.2Et6L7aAdKJsj9ajRjCuXCCOdqbImHCiyP8VpsgsdQDPjHC4bI_Wo8w.GQ61oenekBSl5PdC0n1U4kkIYNs7pYGNvf50GxP4QeU	31
9	Брюки Eleventy из шерсти и кашемира	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/bryuki_eleventy_iz_shersti_i_kashemira_34_7862474789?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	19800	2025-12-22 23:20:54.310416	Брюки Eleventy из шерсти и кашемира, размер 34 (L). Глубокий синий цвет, классический стиль. Изготовлены из качественных материалов для комфорта и долговечности.	https://60.img.avito.st/image/1/1.KuxQVraAhgVG9iQECHpOvRf3hAHi4YIF4obnAeJVh6fl9YIfRvYkBOY.oW_1ldHHBrvVPL3fCNld56DdwyVCDV_GntdUu-Dru9w	34
10	Худи Eleventy из материалов Loro Piana	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/hudi_eleventy_iz_materialov_loro_piana_sm3xl_7798471548?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	20250	2025-12-22 23:20:55.729927	Худи Eleventy из материалов Loro Piana серого цвета, размер (S, M,3XL). Изготовлено из хлопка с добавлением полиэстера для комфорта и долговечности. Новая с биркой.	https://80.img.avito.st/image/1/1.C9rhDraApzP3rgUy-34H1bqvpTdTuaMzU97GN1MNppFUraMp964FMlc.R3ZLtUYR4D8JhGStH9i-Ks0wazkiKpDPp8D0mQebgps	S,M,3XL
11	Джинсы Eleventy	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/dzhinsy_eleventy_31_7862425464?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	13500	2025-12-22 23:20:57.385084	Продаются новые джинсы Eleventy серого цвета. Размер 31 (S). Изготовлены из качественного хлопка. Джинсы имеют потертости и небрежные швы, что придаёт им современный вид.	https://30.img.avito.st/image/1/1.bE12BraAwKRgpmKlIncKcjGnwqDEscSkxNahoMQFwQbDpcS-YKZipcA.TI7zfAhalYeUOqHx_E0xixVo0zwodJUwKgqBHXFH4Lk?cqp=2.31EmCLg6ik3oatt1ttbFq_ajuGsz9wCshVqsaNgtLVVqtiwIcdxsWidTBGP4W2gjZpwuVqcdzwQCR5DnUbaoBbU1	31
12	Спортивные брюки Eleventy из хлопка	2	https://www.avito.ru/moskva/odezhda_obuv_aksessuary/sportivnye_bryuki_eleventy_iz_hlopka_sl_7798484655?slocation=621540&context=H4sIAAAAAAAA_wE_AMD_YToyOntzOjEzOiJsb2NhbFByaW9yaXR5IjtiOjA7czoxOiJ4IjtzOjE2OiJzUlBHaFZQNkdHVXFPMTJXIjt9cm-JDT8AAAA	15000	2025-12-22 23:20:58.876949	Спортивные брюки Eleventy из натурального хлопка бежевого цвета. Размеры — S, L. Брюки новые, с бирками, подходят для активного образа жизни благодаря прочному материалу и легкости.	https://80.img.avito.st/image/1/1.IIti_LaAjGJ0XC5jLtxMmjhdjmbQS4hi0CztZtD_jcDXX4h4dFwuY9Q.X4VDH-KZ7cYA5OLA_wR8FQiLw_SxVY_RhnhNZ_qC1mI	S,L
\.


--
-- Name: categories_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pro100kir2
--

SELECT pg_catalog.setval('public.categories_id_seq', 4, true);


--
-- Name: gigachat_token_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pro100kir2
--

SELECT pg_catalog.setval('public.gigachat_token_id_seq', 14, true);


--
-- Name: products_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pro100kir2
--

SELECT pg_catalog.setval('public.products_id_seq', 12, true);


--
-- Name: categories categories_name_key; Type: CONSTRAINT; Schema: public; Owner: pro100kir2
--

ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_name_key UNIQUE (name);


--
-- Name: categories categories_pkey; Type: CONSTRAINT; Schema: public; Owner: pro100kir2
--

ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_pkey PRIMARY KEY (id);


--
-- Name: gigachat_token gigachat_token_pkey; Type: CONSTRAINT; Schema: public; Owner: pro100kir2
--

ALTER TABLE ONLY public.gigachat_token
    ADD CONSTRAINT gigachat_token_pkey PRIMARY KEY (id);


--
-- Name: products products_avito_url_key; Type: CONSTRAINT; Schema: public; Owner: pro100kir2
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_avito_url_key UNIQUE (avito_url);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: pro100kir2
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- Name: idx_products_title_trgm; Type: INDEX; Schema: public; Owner: pro100kir2
--

CREATE INDEX idx_products_title_trgm ON public.products USING gin (title public.gin_trgm_ops);


--
-- Name: products products_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pro100kir2
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.categories(id);


--
-- PostgreSQL database dump complete
--

\unrestrict cQHhn31VKBeOjvfonqCgJTAbIBf4g6I8uwhrB15R79Sz4qltemDjgcrGUzizdqv


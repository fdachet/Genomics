#Proteindomain           IDR = Context dependent use   (can have different uses and foldings depending of the millieu condition and what interract with it), tool multi-use
#rm(list = ls(all = TRUE))
# load("C:\\Users\\Dash\\Desktop\\A_ProteinDomains\\CCRCC_Test\\R_End_Pz3on5_GeneList_CCRCC_Test.rdata")   # must create/load object named 'sa'
options(stringsAsFactors = FALSE)
library(IsoformSwitchAnalyzeR);library(ggplot2);library(dplyr)
GENESWITCH_DIR <- "C:\\A_ProteinDomains\\CCRCC_Global\\Output_CCRCC\\GeneSwitch_2277"   #→ PUT also the sequences analyzed  ..SwitchXX.. used in this folder
setwd(GENESWITCH_DIR)

#READ SEQUENCE FILES USED FOR ANNOTATIONS on the specific SWITCHXX file used
if (Mode!="Genelist"){
Sequence_GeneExpcutoff<-0.5     #  THE minimal IF  USED FOR THE LIST OF SEQUENCES ANALYZED PREVIOUSLY  To remove Isoform with minor contribution, default = 0.05     (the isoform need to compose more than 5% of the total gene expression)   (READ SEQUENCE FILES USED FOR ANNOTATIONS)
Sequence_IsoExpcutoff<-0.05     #  THE minimal IF  USED FOR THE LIST OF SEQUENCES ANALYZED PREVIOUSLY  To remove Isoform with minor contribution, default = 0.05     (the isoform need to compose more than 5% of the total gene expression)   (READ SEQUENCE FILES USED FOR ANNOTATIONS)
Sequence_IFcutoff<-0.05     #  THE minimal IF  USED FOR THE LIST OF SEQUENCES ANALYZED PREVIOUSLY  To remove Isoform with minor contribution, default = 0.05     (the isoform need to compose more than 5% of the total gene expression)   (READ SEQUENCE FILES USED FOR ANNOTATIONS)
Sequence_Alpha<-0.05 # THE ALPHA USED FOR THE LIST OF SEQUENCES ANALYZED PREVIOUSLY  (READ SEQUENCE FILES USED FOR ANNOTATIONS)  usually 0.05
Sequence_DIF<-0.1 # THE DIF  USED FOR THE LIST OF SEQUENCES ANALYZED PREVIOUSLY   (READ SEQUENCE FILES USED FOR ANNOTATIONS) usually 0.1
}
#THRESOLD SIGNIFICANCE ASKED BY THE USER
Test_Alpha<-0.05   # THE ALPHA USED FOR declaring a isoform as significantly DU    usualy  0.05
Test_DIF<-0.1     # THE DIF  USED FOR declaring a isoform as significantly DU  usualy 0.1
Test_IFcutoff<-0.1       #  THE minimal IF  USED before declaring a isoform as significantly DU    (e.g. 5%  the isoform needs to be more than 5% expresion of the gene expression)   usualy 0.1

#THRESOLD FOR PLOTTING  ASKED BY THE USER
Plot_Alpha<-0.05   # THE ALPHA USED FOR declaring a isoform as significantly DU
Plot_DIF<-0.10     # THE DIF  USED FOR declaring a isoform as significantly DU
Plot_IFcutoff<-0.10       #  THE minimal IF  USED before declaring a isoform as significantly DU    (e.g. 5%  the isoform needs to be more than 5% expresion of the gene expression)
Plot_InterestingIsoExpcutoff<-1     #  THE minimal expression of interresting isoform to be plotted
Error_B<-FALSE

CPAT_FILE    <- file.path(GENESWITCH_DIR, "Result_CPAT.txt")
IUPRED_FILE  <- file.path(GENESWITCH_DIR, "Result_IUPRED2A.txt")
SIGNALP_FILE <- file.path(GENESWITCH_DIR, "Result_SignalP.txt")
PFAM_FILE    <- file.path(GENESWITCH_DIR, "Result_PFAM.txt")
TMHMM_FILE   <- file.path(GENESWITCH_DIR, "Result_DeepTMHMM.gff3")
#DEEPLOC2.1_FILE <- file.path(GENESWITCH_DIR, "Result_DeepLoc2.1.txt")
DEEPLOC2.0_FILE <- file.path(GENESWITCH_DIR, "Result_DeepLoc2.0.txt")
DEEPLOC_Version <- 2 #  2   (or 2.1 ?)       ← the version needed is the 2 

MaxGenesToPlot  <- 3000    # Maximum quantity of genes plotted →  based on the best isoform usage switch q values
CPATcodingCutoff  <-  0.364   # 0.364  is recommended by the people that developped CPAT  but 0.725 is recommended by people that developped Isoformswithanalyzer    , Score < 0.364 indicates noncoding
Name_Study_Detailled <- Name_Study_Detailled  ;   print(Name_Study_Detailled )
Temp_iso<-which(sa$isoformFeatures$isoform_switch_q_value<Sequence_Alpha&abs(sa$isoformFeatures$dIF)>Sequence_DIF)
Temp_Gene<-unique(sa$isoformFeatures$gene_id[Temp_iso])
if(Mode=="GeneList"){Temp_Gene<-unique(sa$isoformFeatures$gene_id)}
#Temp_iso<-sa$isoformFeatures$isoform_id[which(sa$isoformFeatures$gene_id %in%Temp_Gene)]   #  For isoformes DU and Not DU
if(Mode!="GeneList")
{
Temp1<-paste("Original filtration of the sa object: genes=",length(unique(sa$isoformFeatures$gene_id)),"isoformes=",dim(sa)[1], "All the genes have expression superior to:",Prefilter_GENE_EXPR_CUTOFF,", each isoform have expression superior to:",Prefilter_ISOFORM_EXPR_CUTOFF,". Each isoform is at least:",Prefilter_IF_CUTOFF*100,"% of the gene")
Temp2<-paste0("Sequences analyzed: The  thresold used for Sequence anotation is until pvalue of ",Sequence_Alpha," with a minimal Delta IF of ",Sequence_DIF,". Each isoform is at least: ",Sequence_IFcutoff*100,"% of the gene →   Signif. DU genes=",length(unique(sa$isoformFeatures$gene_id[which(sa$isoformFeatures$isoform_switch_q_value<Sequence_Alpha&abs(sa$isoformFeatures$dIF)>Sequence_DIF)]))," / DU isoforms=",length(Temp_iso),"   (from DU genes: isoforms DU+isoforms nonDU = ",length(sa$isoformFeatures$isoform_id[which(sa$isoformFeatures$gene_id %in%Temp_Gene)]) ,")")
Temp3<-paste0("The  thresold for significance of Isoform DU is at pvalue=",Test_Alpha," with a minimal Delta IF of ",Test_DIF,". Only Isoforms with ",Test_IFcutoff*100,"% or more of the gene total expression are considered   → DU genes=",length(unique(sa$isoformFeatures$gene_id[which(sa$isoformFeatures$isoform_switch_q_value<Test_Alpha&abs(sa$isoformFeatures$dIF)>Test_DIF&    sa$isoformFeatures$IF_overall  >Test_IFcutoff)]))," / DU isoforms=",length(sa$isoformFeatures$gene_id[which(sa$isoformFeatures$isoform_switch_q_value<Test_Alpha&abs(sa$isoformFeatures$dIF)>Test_DIF  &   sa$isoformFeatures$IF_overall     >Test_IFcutoff  )]))
Temp4<-paste("the p thresold for a gene to be plotted is:",  Plot_Alpha ,  "With at least one isoform with a change of IF:",Plot_DIF , "and an IF value of :",Plot_IFcutoff," resulting in:",length(unique(sa$isoformFeatures$gene_id[which(sa$isoformFeatures$isoform_switch_q_value<=Plot_Alpha&abs(sa$isoformFeatures$dIF)>=Plot_DIF&sa$isoformFeatures$IF_overall>=Plot_IFcutoff)])),"Genes able to be plotted with a maximal of genes to plot:",MaxGenesToPlot,". The interresting genes will be plotted with isofomrs expression superior to:",Plot_InterestingIsoExpcutoff) 
print(Temp1);print(""); print(Temp2); print("");print(Temp3);print(""); print(Temp4) 
if(Sequence_Alpha<max(Test_Alpha,Plot_Alpha) | Sequence_DIF>min(Test_DIF,Plot_DIF)|Plot_InterestingIsoExpcutoff<Sequence_IsoExpcutoff | Sequence_IFcutoff > min(Test_IFcutoff,Plot_IFcutoff)){print("**************************");print("!!!! ERROR  !!!!!  the thresolds used to test sequence DU significance or plot the genes is lower than the thresolds used for sequences anotations ");print("**************************");Error_B<-TRUE} 
if(max(sa$isoformFeatures$isoform_switch_q_value,sa$isoformFeatures$isoform_switch_q_value,na.rm = TRUE)<0.49){print("!!!!!!!!!! ERROR !!!!! sa object seems to have been truncated based on qvalues")}
if(Error_B){stop()}
}
Print1k_B<-F;  Print2k_B<-T;   Print4k_B<-T;       Print8k_B<-F


PLOT_PNG_DIR_1k<-PLOT_PNG_DIR_2k<-PLOT_PNG_DIR_4k<-PLOT_PNG_DIR_8k<-PLOT_PNG_BEST_DIR_1k<-PLOT_PNG_BEST_DIR_2k<-PLOT_PNG_BEST_DIR_4k<-PLOT_PNG_BEST_DIR_8k<-NULL
if( Print1k_B){PLOT_PNG_DIR_1k  <- file.path(GENESWITCH_DIR, "Plots/Plots_PNG_1k"); dir.create(PLOT_PNG_DIR_1k, recursive = TRUE, showWarnings = FALSE)}
if( Print2k_B){PLOT_PNG_DIR_2k  <- file.path(GENESWITCH_DIR, "Plots/Plots_PNG_2k"); dir.create(PLOT_PNG_DIR_2k, recursive = TRUE, showWarnings = FALSE)}
if( Print4k_B){PLOT_PNG_DIR_4k  <- file.path(GENESWITCH_DIR, "Plots/Plots_PNG_4k"); dir.create(PLOT_PNG_DIR_4k, recursive = TRUE, showWarnings = FALSE)}
if( Print8k_B){PLOT_PNG_DIR_8k  <- file.path(GENESWITCH_DIR, "Plots/Plots_PNG_8k"); dir.create(PLOT_PNG_DIR_8k, recursive = TRUE, showWarnings = FALSE)}
if( Print1k_B){PLOT_PNG_BEST_DIR_1k  <- file.path(GENESWITCH_DIR, "BestPlots/BestPlots_PNG_1k"); dir.create(PLOT_PNG_BEST_DIR_1k, recursive = TRUE, showWarnings = FALSE)}
if( Print2k_B){PLOT_PNG_BEST_DIR_2k  <- file.path(GENESWITCH_DIR, "BestPlots/BestPlots_PNG_2k"); dir.create(PLOT_PNG_BEST_DIR_2k, recursive = TRUE, showWarnings = FALSE)}
if( Print4k_B){PLOT_PNG_BEST_DIR_4k  <- file.path(GENESWITCH_DIR, "BestPlots/BestPlots_PNG_4k"); dir.create(PLOT_PNG_BEST_DIR_4k, recursive = TRUE, showWarnings = FALSE)}
if( Print8k_B){PLOT_PNG_BEST_DIR_8k  <- file.path(GENESWITCH_DIR, "BestPlots/BestPlots_PNG_8k"); dir.create(PLOT_PNG_BEST_DIR_8k, recursive = TRUE, showWarnings = FALSE)}


#Modification Deeploc2.1  →  Deeploc2.0
if(DEEPLOC_Version==2.1)
{
temp <- c(   "Protein_ID", "Localizations", "Signals", "Cytoplasm", "Nucleus", "Extracellular",   "Cell membrane", "Mitochondrion", "Plastid", "Endoplasmic reticulum", "Lysosome/Vacuole", "Golgi apparatus", "Peroxisome")
DEEPLOC2.1_FILE<-read.table(DEEPLOC2.1_FILE, header=TRUE, sep=",", check.names=FALSE, stringsAsFactors=FALSE)
DEEPLOC2.1_FILE<- DEEPLOC2.1_FILE[,temp,drop=FALSE]
write.table(DEEPLOC2.1_FILE,file=file.path(GENESWITCH_DIR, "Input", "Result_DeepLoc2.0.txt"), sep=",", row.names=FALSE, quote=FALSE)
}

if (Mode=="Diff"||Mode=="Global")
{
temp <- which(sa$isoformFeatures$isoform_switch_q_value <= Plot_Alpha & abs( sa$isoformFeatures$dIF) >= Plot_DIF &  sa$isoformFeatures$IF_overall >= Plot_IFcutoff)
temp <- temp[order(sa$isoformFeatures$isoform_switch_q_value[temp])]
temp1<-min(MaxGenesToPlot ,length( unique(sa$isoformFeatures$gene_id[temp])))
GenesToPlot <- unique(sa$isoformFeatures$gene_id[temp])[1:temp1]
}



if (Mode=="GeneList")
{
GenesToPlot<-unique(sa$isoformFeatures$gene_id)
}

showProgress<-TRUE
if(length(GenesToPlot)==1){showProgress <- FALSE}
if (file.exists(CPAT_FILE  ))  sa <-analyzeCPAT(sa, CPAT_FILE ,codingCutoff = CPATcodingCutoff ,removeNoncodinORFs=FALSE )  else  print(paste("[WARN] CPAT file missing: ", CPAT_FILE))
if (file.exists(IUPRED_FILE))  sa <- analyzeIUPred2A(sa, IUPRED_FILE)  else print(paste("[WARN] IUPred file missing: ", IUPRED_FILE))
if (file.exists(SIGNALP_FILE)) sa <- analyzeSignalP(sa, SIGNALP_FILE) else print(paste("[WARN] SignalP file missing: ", SIGNALP_FILE))
if (file.exists(PFAM_FILE))    sa <- analyzePFAM(sa, PFAM_FILE)       else print(paste("[WARN] PFAM file missing: ", PFAM_FILE))
if (file.exists(TMHMM_FILE))   sa <- analyzeDeepTMHMM(sa, TMHMM_FILE) else print(paste("[WARN] DeepTMHMM file missing: ", TMHMM_FILE))
if (file.exists(DEEPLOC2.0_FILE  ))  sa <-analyzeDeepLoc2(sa,DEEPLOC2.0_FILE )  else  print(paste("[WARN] DEEPLOC2 file missing: ", DEEPLOC2_FILE ))
if (Mode!="GeneList")
{
sa <- analyzeIntronRetention(sa,alpha=    Test_Alpha,   dIFcutoff =Test_DIF,onlySwitchingGenes =TRUE,showProgress=showProgress)
sa<-analyzeAlternativeSplicing(sa,alpha=    Test_Alpha,   dIFcutoff =Test_DIF,onlySwitchingGenes =TRUE,showProgress=showProgress)
}


if (Mode=="GeneList")
{
sa <- analyzeIntronRetention(sa,alpha=   1,   dIFcutoff =0,onlySwitchingGenes =F,showProgress=showProgress)
sa<-analyzeAlternativeSplicing(sa,alpha=    1,   dIFcutoff =0,onlySwitchingGenes =F,showProgress=showProgress)
}
patch_switchPlot_bar_colors <- function(light = "royalblue2", dark = "tomato") {
  ns <- asNamespace("IsoformSwitchAnalyzeR")
  f  <- get("expressionAnalysisPlot", envir = ns)
  src <- paste(deparse(f), collapse = "\n")
  src2 <- gsub(
    'scale_fill_manual\\s*\\(\\s*values\\s*=\\s*c\\s*\\(\\s*["\\\']darkgrey["\\\']\\s*,\\s*["\\\']#333333["\\\']\\s*\\)\\s*\\)',
    sprintf('scale_fill_manual(values = c("%s","%s"))', light, dark),
    src, perl = TRUE, ignore.case = TRUE
  )
  newf <- eval(parse(text = src2), envir = ns)
  environment(newf) <- ns
  assignInNamespace("expressionAnalysisPlot", newf, ns = "IsoformSwitchAnalyzeR")
}

patch_switchPlot_bar_colors("royalblue2", "tomato")  # Just to change the colors of the bar plots (they are grey/back by default)

if (Mode!="GeneList"){Name_Study_Detailled<-paste0(Name_Study,"_Alpha",Test_Alpha,"_DIF",Test_DIF)}
save.image(paste0("R4_Pz5on5_BeforePlotting",Name_Study_Detailled,".rdata"))

Ploteur_fct <- function(GenesToPlot, DIR_1k = NULL, DIR_2k = NULL, DIR_4k = NULL, DIR_8k = NULL)
{
  loc_code <- c(
    "cytoplasm"             = "Cyto",
    "nucleus"               = "Nucl",
    "extracellular"         = "Extra",
    "cell_membrane"         = "Memb",
    "mitochondrion"         = "Mito",
    "plastid"               = "Plast",
    "chloroplast"           = "Chloro",
    "endoplasmic_reticulum" = "ER",
    "lysosome_vacuole"      = "Lyso",
    "golgi_apparatus"       = "Golgi",
    "peroxisome"            = "Perox"
  )

  split_locs <- function(x)
  {
    p <- unlist(strsplit(x, ",", fixed = TRUE))
    p <- trimws(p)
    p <- tolower(p)
    p <- gsub("[/ ]+", "_", p)
    p <- gsub("_+", "_", p)
    p[p != ""]
  }

  clean_gene_name <- function(x)
  {
    x <- trimws(x)
    x <- gsub("[^A-Za-z0-9]+", "-", x)
    gsub("^-+|-+$", "", x)
  }

  make_exists_env <- function(d)
  {
    e <- new.env(hash = TRUE, parent = emptyenv())
    if (!is.null(d)) {
      f <- list.files(d, pattern = "\\.png$", ignore.case = TRUE)
      if (length(f)) for (z in f) assign(z, TRUE, envir = e)
    }
    e
  }

  already_exists <- function(e, f)
  {
    exists(f, envir = e, inherits = FALSE)
  }

  mark_exists <- function(e, f)
  {
    assign(f, TRUE, envir = e)
  }

  iso <- sa$isoformFeatures[, c("gene_id", "gene_name", "sub_cell_location")]
  iso$gene_id <- as.character(iso$gene_id)
  iso$gene_name <- as.character(iso$gene_name)
  iso$sub_cell_location <- as.character(iso$sub_cell_location)

  genes_u <- unique(as.character(GenesToPlot))
  iso <- iso[iso$gene_id %in% genes_u, , drop = FALSE]
  sp <- split(iso, iso$gene_id, drop = TRUE)

  base_name_map <- setNames(character(length(genes_u)), genes_u)

  for (g in genes_u)
  {
    df <- sp[[g]]

    gn <- df$gene_name
    gn <- gn[!is.na(gn) & nzchar(gn)]
    gname <- if (length(gn)) clean_gene_name(gn[1]) else "NA"

    seen <- character(0)
    for (x in df$sub_cell_location)
    {
      locs <- split_locs(x)
      for (loc in locs) if (!(loc %in% seen)) seen <- c(seen, loc)
    }

    codes <- loc_code[seen]
    codes <- codes[!is.na(codes)]
    tag <- if (length(codes)) paste0(codes, collapse = "") else "NoLoc"

    base_name_map[g] <- paste0(gname, "_", g, "_", tag)
  }

  existing_1k <- make_exists_env(DIR_1k)
  existing_2k <- make_exists_env(DIR_2k)
  existing_4k <- make_exists_env(DIR_4k)
  existing_8k <- make_exists_env(DIR_8k)

  for (indice in seq_along(GenesToPlot))
  {
    gene_e.c. <- as.character(GenesToPlot[indice])
    base_name <- base_name_map[gene_e.c.]
    file_name <- paste0(base_name, ".png")

    need_1k <- Print1k_B && !is.null(DIR_1k) && !already_exists(existing_1k, file_name)
    need_2k <- Print2k_B && !is.null(DIR_2k) && !already_exists(existing_2k, file_name)
    need_4k <- Print4k_B && !is.null(DIR_4k) && !already_exists(existing_4k, file_name)
    need_8k <- Print8k_B && !is.null(DIR_8k) && !already_exists(existing_8k, file_name)

    cat(indice, "/", length(GenesToPlot), " ", base_name,
        " 1k=", need_1k, " 2k=", need_2k, " 4k=", need_4k, " 8k=", need_8k, "\n", sep = "")
    flush.console()

    if (need_1k)
    {
      png(file.path(DIR_1k, file_name),
          width = 960, height = 540, units = "px", pointsize = 5, res = 120)
      tryCatch(
        suppressWarnings(
          switchPlot(
            sa,
            gene = gene_e.c.,
            IFcutoff = Sequence_IFcutoff,
            dIFcutoff = Sequence_DIF,
            alphas = c(Sequence_Alpha, Sequence_Alpha / 100)
          )
        ),
        finally = dev.off()
      )
      mark_exists(existing_1k, file_name)
    }

    if (need_2k)
    {
      png(file.path(DIR_2k, file_name),
          width = 1920, height = 1080, units = "px", pointsize = 6, res = 160)
      tryCatch(
        suppressWarnings(
          switchPlot(
            sa,
            gene = gene_e.c.,
            IFcutoff = Sequence_IFcutoff,
            dIFcutoff = Sequence_DIF,
            alphas = c(Sequence_Alpha, Sequence_Alpha / 100)
          )
        ),
        finally = dev.off()
      )
      mark_exists(existing_2k, file_name)
    }

    if (need_4k)
    {
      png(file.path(DIR_4k, file_name),
          width = 1920 * 2, height = 1080 * 2, units = "px", pointsize = 6, res = 200)
      tryCatch(
        suppressWarnings(
          switchPlot(
            sa,
            gene = gene_e.c.,
            IFcutoff = Sequence_IFcutoff,
            dIFcutoff = Sequence_DIF,
            alphas = c(Sequence_Alpha, Sequence_Alpha / 100)
          )
        ),
        finally = dev.off()
      )
      mark_exists(existing_4k, file_name)
    }

    if (need_8k)
    {
      png(file.path(DIR_8k, file_name),
          width = 1920 * 4, height = 1080 * 4, units = "px", pointsize = 7, res = 210)
      tryCatch(
        suppressWarnings(
          switchPlot(
            sa,
            gene = gene_e.c.,
            IFcutoff = Sequence_IFcutoff,
            dIFcutoff = Sequence_DIF,
            alphas = c(Sequence_Alpha, Sequence_Alpha / 100)
          )
        ),
        finally = dev.off()
      )
      mark_exists(existing_8k, file_name)
    }
  }
}


Ploteur_fct(GenesToPlot,PLOT_PNG_DIR_1k,PLOT_PNG_DIR_2k,PLOT_PNG_DIR_4k,PLOT_PNG_DIR_8k)
#  How many transcripts contain how many introns (  e.g.:  0  1? , 2?...)
#        ATSS :Alternative Transcription Start Site
#  AS : Alternative Splicing
# ATTS : Alternative Termination Site
png(file="IntronRetention.png",width=1920 ,height=1080,units="px",pointsize=12,res=200)
tab <- table(sa$AlternativeSplicingAnalysis$IR); x <- as.numeric(names(tab)); y <- as.numeric(tab)
ord <- order(x); x <- x[ord]; y <- y[ord]
bp <- barplot(y, names.arg=x, xlab="Number of Intron per gene", ylab="Quantity of genes", main="Quantity of genes (Number of Intron per gene)", ylim=c(0, max(y)*1.1))
text(bp, y,labels=y, pos=3, cex=0.8)
dev.off()


"#keep genes only if:  at least 2 isoforms pass the IF cutoff in condition 1,
at least 2 isoforms pass the IF cutoff in condition 2,
and at least 1 isoform is a significant switching isoform by q-value and dIF."
iso <- sa$isoformFeatures

keep_gene_one_group <- function(df, Plot_IFcutoff, Plot_Alpha, Plot_DIF, Plot_InterestingIsoExpcutoff) {
  expr_ok <- !is.na(df$iso_value_1) & df$iso_value_1 >= Plot_InterestingIsoExpcutoff &
             !is.na(df$iso_value_2) & df$iso_value_2 >= Plot_InterestingIsoExpcutoff

  bg1 <- !is.na(df$IF1) & df$IF1 >= Plot_IFcutoff & expr_ok
  bg2 <- !is.na(df$IF2) & df$IF2 >= Plot_IFcutoff & expr_ok

  sw <- !is.na(df$isoform_switch_q_value) &
        df$isoform_switch_q_value <= Plot_Alpha &
        !is.na(df$dIF) &
        abs(df$dIF) >= Plot_DIF &
        expr_ok &
        (bg1 | bg2)

  (sum(bg1) >= 2) && (sum(bg2) >= 2) && any(sw)
}

grp <- interaction(iso$condition_1, iso$condition_2, iso$gene_id, drop = TRUE)
sp <- split(iso, grp, drop = TRUE)

pass <- vapply(
  sp,
  keep_gene_one_group,
  logical(1),
  Plot_IFcutoff = Plot_IFcutoff,
  Plot_Alpha = Plot_Alpha,
  Plot_DIF = Plot_DIF,
  Plot_InterestingIsoExpcutoff = Plot_InterestingIsoExpcutoff
)

if (any(pass)) {
  Genes_matching <- unique(vapply(sp[pass], function(df) df$gene_id[1], character(1)))
} else {
  Genes_matching <- character(0)
}

Ploteur_fct(Genes_matching,PLOT_PNG_BEST_DIR_1k,PLOT_PNG_BEST_DIR_2k,PLOT_PNG_BEST_DIR_4k,PLOT_PNG_BEST_DIR_8k)









if(Mode!="GeneList"){try(sa <- analyzeSwitchConsequences(sa,consequencesToAnalyze = 'all',alpha = Test_Alpha,dIFcutoff = Test_DIF))}
if(Mode=="GeneList"){try(sa <- analyzeSwitchConsequences(sa,consequencesToAnalyze = 'all',alpha = 1,dIFcutoff = 0.1))}
switchConsequence_map <- c(
"Extracellular length gain"="ExtraCellular","Extracellular length loss"="ExtraCellular","Extracellular region gain"="ExtraCellular","Extracellular region loss"="ExtraCellular",
"IDR gain"="IDR","IDR length gain"="IDR","IDR length loss"="IDR","IDR loss"="IDR","IDR switch"="IDR","IDR w binding region gain"="IDR","IDR w binding region loss"="IDR","IDR w binding region switch"="IDR",
"SubCell location cyto gain"="IntraCellular","SubCell location cyto loss"="IntraCellular","SubCell location ext cell gain"="IntraCellular","SubCell location ext cell loss"="IntraCellular","SubCell location gain"="IntraCellular","SubCell location loss"="IntraCellular","SubCell location memb gain"="IntraCellular","SubCell location memb loss"="IntraCellular","SubCell location nucl gain"="IntraCellular","SubCell location nucl loss"="IntraCellular","SubCell location switch"="IntraCellular","Intracellular length gain"="IntraCellular","Intracellular length loss"="IntraCellular","Intracellular region gain"="IntraCellular","Intracellular region loss"="IntraCellular",
"Intron retention gain"="Intron","Intron retention loss"="Intron","Intron retention switch"="Intron",
"NMD sensitive"="NonCoding","Transcript is Noncoding"="NonCoding",
"Complete ORF gain"="ORF","Complete ORF loss"="ORF","Domain gain"="ORF","Domain length gain"="ORF","Domain length loss"="ORF","Domain loss"="ORF","Domain non-reference isotype gain"="ORF","Domain non-reference isotype loss"="ORF","Domain switch"="ORF","Exon gain"="ORF","Exon loss"="ORF",
"3UTR is longer"="UTR","3UTR is shorter"="UTR","5UTR is longer"="UTR","5UTR is shorter"="UTR",
"Last exon more downstream"="Divers","Last exon more upstream"="Divers","Length gain"="Divers","Length loss"="Divers","Mixed domain isotype changes"="Divers","Mixed Domain length differences"="Divers","NA"="Divers","NMD insensitive"="Divers","ORF is longer"="Divers","ORF is shorter"="Divers","Signal peptide gain"="Divers","Signal peptide loss"="Divers","switchConsequence"="Divers","Topology complexity gain"="Divers","Topology complexity loss"="Divers","Transcript is coding"="Divers","Tss more downstream"="Divers","Tss more upstream"="Divers","Tts more downstream"="Divers","Tts more upstream"="Divers"
)

tmp_switchConsequence <- as.character(sa$switchConsequence$switchConsequence)
tmp_switchConsequence[is.na(tmp_switchConsequence)] <- "NA"

sa$switchConsequence$switchConsequence_Simple <- unname(switchConsequence_map[tmp_switchConsequence])
sa$switchConsequence$switchConsequence_Simple[is.na(sa$switchConsequence$switchConsequence_Simple)] <- "Divers"

sa$switchConsequence$switchConsequence_Simple <- factor(
    sa$switchConsequence$switchConsequence_Simple,
    levels = c("UTR","ORF","ExtraCellular","IDR","IntraCellular","Intron","NonCoding","Divers")
)
write.table(sa$switchConsequence,file="SwitchConsequence.tabtxt",sep='\t',col.names=NA)
png(file="SplicingSummary.png",width=1920 ,height=1080,units="px",pointsize=6,res=160)
try(extractSplicingSummary(sa,alpha = Sequence_Alpha,dIFcutoff = Sequence_DIF))
dev.off()

png(file="SplicingEnrichment.png",width=1920 ,height=1080,units="px",pointsize=6,res=160)
try(extractSplicingEnrichment( sa,    splicingToAnalyze='all', alpha = Sequence_Alpha,dIFcutoff = Sequence_DIF  ))
dev.off()

png(file="SplicingGenomeWide.png",width=1920 ,height=1080,units="px",pointsize=6,res=160)
try(extractSplicingGenomeWide( sa,   featureToExtract = 'all',  plot=TRUE,returnResult=FALSE,alpha = Sequence_Alpha,dIFcutoff = Sequence_DIF))
dev.off()
png(file="SplicingIsoformUsage.png",width=1920 ,height=1080,units="px",pointsize=6,res=160)
try(extractSplicingGenomeWide( sa,   featureToExtract = 'isoformUsage',  plot=TRUE,returnResult=FALSE,alpha = Sequence_Alpha,dIFcutoff = Sequence_DIF))
dev.off()







df <- extractSubCellShifts(sa, plotGenes =TRUE, returnResult = TRUE) %>%
  mutate(
    value = if (TRUE) n_genes else n_switch,
    comparison = paste(condition_1, "vs", condition_2),
    location_gain = as.character(location_gain),
    location_loss = as.character(location_loss)
  )

y_label <- if (TRUE) "Number of genes" else "Number of isoform switches"
output_png <- if (TRUE) {
  "Subcellular_location_shifts_gradient_plus_numbers_genes.png"
} else {
  "Subcellular_location_shifts_gradient_plus_numbers_switches.png"
}

p <- ggplot(df, aes(x = location_loss, y = location_gain, fill = value)) +
  geom_tile(color = "black") +
  geom_text(aes(label = value), size = 5) +
  facet_wrap(~ comparison) +
  scale_fill_gradient(low = "white", high = "red", name = y_label) +
  labs(
    title = "Subcellular localization shifts",
    subtitle = y_label,
    x = "Location lost",
    y = "Location gained"
  ) +
  theme_bw(base_size = 14) +
  theme(
    axis.text.x = element_text(angle = 45, hjust = 1),
    panel.grid = element_blank()
  )

print(p)

ggsave(output_png, p, width = 10, height = 8, dpi = 300)

write.table(
  df,
  file = "Subcellular_location_shifts_gradient_plus_numbers_table.tsv",
  sep = "\t",
  quote = FALSE,
  row.names = FALSE
)

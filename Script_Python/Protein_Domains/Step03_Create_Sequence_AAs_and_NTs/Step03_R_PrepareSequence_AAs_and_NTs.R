#Proteindomain
rm(list = ls(all = TRUE))
#load("P:\\Biostat\\RNASeq\\CCRCC\\A_ProteinDomains\\CCRCC_GlobalInput\\R_AfterImporteSa_CCRCC_A_ProteinDomains_GlobalInput.rdata")
# Load Rdata R1  if present
Name_Study<-"CCRCC"
setwd("C:\\A_ProteinDomains\\CCRCC_Global")  # This is the root folder and need to contain the folder 'Input' where the input files are located  (5 analysis result_ files : Design, ISoform count matrix, DE gene significance(from Deseq2),mergedFA and mergedGTF))
RUN_DIR <- getwd()
library(IsoformSwitchAnalyzeR)



DESIGN_FILE      <- file.path(RUN_DIR, "Input", "Design_Kidney.tabtxt")              #  NPO:         Columns are:          sampleID           condition            designMatrix must contain columns: sampleID and condition, extra columns are for nuisance covariates such as batch effects and patient ID
ISO_COUNTS_FILE  <- file.path(RUN_DIR, "Input", "isoform_count_matrix.tsv")
DE_Gene_Significance <- file.path(RUN_DIR, "Input", "DE_Gene_Significance.tabtxt")                     #  DE Genes significances (first column GeneID  second column significance of DE)
MERGED_GTF       <- file.path(RUN_DIR, "Input", "merged.gtf")
MERGED_FA        <- file.path(RUN_DIR, "Input", "merged.fa")
GeneList<- file.path(RUN_DIR, "Input", "Genelist_155Genes_literature.txt")   # It should contains the Ensembl Ids , found in the stringtie GTF     'ref_gene_id'

METHOD <- "satuRn"   #  if more than 8 samples: "satuRn"         if less than 8 samples: "DEXSeq"     Dexseq is slow when there is lot of samples, e.g. for 8 or more samples use  Saturn will be faster 
Mode<-"GeneList"      #  "Diff"  or    "GeneList" or "Global"     GeneList → Need to have a gene list (identification of genes based on GeneList.txt       Global→ maximise the sa objet so can be use for Diff or Geneliast after the isoform test

#IF Correspond to ISOFORM FRACTION :  expression of the transcript divided by expression of the gene (sum of all isoforn experession)

comparisonsToMake <- data.frame( condition_1 = "NORMAL", condition_2 = "CCRCC"  )                #  the condition 1 correspond to the reference   e.g  data.frame( condition_1 = c("B", "D"), condition_2 = c("A", "C") )   → s it will do 2 analyses stored in the same sa object, the first analyzis using B as reference and testing A    and the second analyzis using D as reference and testing C         for concatenated e.g. reference 'B and A" Vs 'C'  the design matrix need to be rewritten and concatenate B with A
#Prefilter settings  do lenian thresold to keep the max isoforms in the sa object  UDE DIAGNOSTIC PLOTS !!!
Prefilter_GENE_EXPR_CUTOFF            <- 0.5     #remove gene from the sa object  with low expression (the unit should be in TPM/RPKM? ?  )  default = 1
Prefilter_ISOFORM_EXPR_CUTOFF         <- 0.05                   #remove transcripts with low expression from the sa object (the unit should be in TPM/RPKM ?  )    Default=0 (only remove completely unusued transcript)     in  at least 1 SAMPLE the transccript must be expressed more than that .
Prefilter_IF_CUTOFF      <- 0.05               # ISOFORM FRACTION cutoff to remove isoform from the sa object that are very small part of the gene expression  (e.g. 0.1  → the transcript need to be more than 10% of total transcrip expression in either control or test     if 0.02 in ctrrl and 0.09 in ctrl it is removed from analysis)    default =0  (remove non useful transcripts)
# Switch Test  Diff test settings to declare significance
Test_Alpha <- 0.1  # → during Switch Test only used in DIFF MODE using reduceToSwitchingGenes=TRUE   Determine significant switch, e.g. pvalue,  less than 0.05 is significant  The results of the test are dependant of the isoforms left after filtering by prefilter
Test_DIF   <-  0.05 # → during Switch Test  only used in DIFF MODE using  reduceToSwitchingGenes=TRUE   determine the cuttof on the effect as change in ISOFORM FRACTION between the 2 conditions, comparable to a thresold on fold change  default 0.1      The results of the test are dependant of the isoforms left after filtering by prefilter
# Extract sequence settings
Sequence_Alpha <-0.05
Sequence_DIF   <-  0.10 # → during Switch Test  only used in DIFF MODE using  reduceToSwitchingGenes=TRUE   determine the cuttof on the effect as change in ISOFORM FRACTION between the 2 conditions, comparable to a thresold on fold change  default 0.1      The results of the test are dependant of the isoforms left after filtering by prefilter



OUT_DIR <- file.path(RUN_DIR, paste0("Output_",Name_Study))
SEQ_DIR <- file.path(OUT_DIR, "Sequences")
DIAG_DIR<- file.path(OUT_DIR, "Diagnostic")
dir.create(SEQ_DIR, recursive = TRUE, showWarnings = FALSE)
dir.create(DIAG_DIR, showWarnings=FALSE, recursive=TRUE)
comparisonsToMake[]<-lapply(comparisonsToMake,toupper)
design <- read.table(DESIGN_FILE, header=TRUE, sep="\t", stringsAsFactors=FALSE, check.names=FALSE)
design$sampleID  <- toupper(trimws(design$sampleID))
design$condition <- toupper(trimws(design$condition))
#design$batch     <- toupper(trimws(design$batch))

iso_mat <- as.matrix(read.table(ISO_COUNTS_FILE, header=TRUE, sep="\t",
                                stringsAsFactors=FALSE, check.names=FALSE, row.names=1))
storage.mode(iso_mat) <- "numeric"
iso_mat[is.na(iso_mat)] <- 0
colnames(iso_mat) <- toupper(trimws(colnames(iso_mat)))

if (anyDuplicated(design$sampleID)) stop("Duplicate sampleID in design.")
if (anyDuplicated(colnames(iso_mat))) stop("Duplicate sample columns in iso_mat.")

miss_in_counts <- setdiff(design$sampleID, colnames(iso_mat))
miss_in_design <- setdiff(colnames(iso_mat), design$sampleID)
if (length(miss_in_counts)) stop("Samples in design missing from iso_mat: ", paste(miss_in_counts, collapse=", "))
if (length(miss_in_design)) stop("Samples in iso_mat missing from design: ", paste(miss_in_design, collapse=", "))

ord <- sort(colnames(iso_mat))              # A->Z by sampleID
iso_mat <- iso_mat[, ord, drop=FALSE]
design  <- design[match(ord, design$sampleID), , drop=FALSE]
rownames(design) <- design$sampleID

if (!identical(design$sampleID, colnames(iso_mat))) stop("Alignment failed after sorting.")
sa <- importRdata(
  isoformCountMatrix            = iso_mat,
  isoformRepExpression          = NULL,
  designMatrix                  = design,
  isoformExonAnnoation          = MERGED_GTF,
  isoformNtFasta                = MERGED_FA,
  fixStringTieAnnotationProblem = TRUE,
  ignoreAfterPeriod             = FALSE,
  estimateDifferentialGeneRange = FALSE,
  showProgress                  = TRUE,
  detectUnwantedEffects         = FALSE,
comparisonsToMake=comparisonsToMake
)
iso_mat<-0; iso_df<-0; gene_mat<-0;gene_df<-0

#DIAGNOSTIC***********************
isoF <- as.data.frame(sa$isoformFeatures, stringsAsFactors=FALSE)
if (!("IF_overall" %in% names(isoF)) && all(c("IF1","IF2") %in% names(isoF))) isoF$IF_overall <- rowMeans(cbind(as.numeric(isoF$IF1), as.numeric(isoF$IF2)), na.rm=TRUE)

rp <- function(v, fn, main, ylab, logy=FALSE, ylim=NULL){
  v <- as.numeric(v); v <- v[is.finite(v)]
  y <- sort(v); x <- seq_along(y)
  if (logy) y <- pmax(y, 1e-12)
  jpeg(fn, width=2200, height=1400, res=220, quality=100)
  par(mar=c(5,5,4,2)+.1)
  plot(x, y, pch=16, cex=.35, main=main, xlab="Quantity (sorted low -> high)", ylab=ylab, log=if(logy) "y" else "", ylim=ylim)
  dev.off()
}
setwd(DIAG_DIR)
rp(isoF$gene_overall_mean,              "01_gene_overall_mean_logY.jpg",        "gene_overall_mean (logY)",        "gene_overall_mean",        TRUE)
rp(2^(abs(isoF$gene_log2_fold_change)),     "02_abs_FC_Gene.jpg",         "abs(FC Gene) (FC 1 to 4)",       "abs(FC_Gene)",FALSE, c(0,4))    #Verify why it is defined between 0 and 1
rp(isoF$iso_overall_mean,               "03_iso_overall_mean_logY.jpg",         "iso_overall_mean (logY)",         "iso_overall_mean",         TRUE)
rp(isoF$IF_overall,                     "04_IF_overall_logY.jpg",               "IF_overall (logY)",               "IF_overall",               TRUE)
rp(abs(isoF$dIF),                       "05_abs_dIF_logY.jpg",                  "abs(dIF) (logY)",                 "abs(dIF)",                 TRUE)
setwd(RUN_DIR)
isoF<-0
add_fake_isoform_for_single_isoform_genes <- function(sa, suffix = "_fake") # sa_filtered_dup <- add_fake_isoform_for_single_isoform_genes(sa_filtered, suffix = "_fake")
{
  feat <- sa$isoformFeatures
  cnt  <- sa$isoformCountMatrix
  gid <- if ("gene_id" %in% names(feat)) "gene_id" else "gene_ref"
  iid <- intersect(c("isoform_id","transcript_id","isoformId"), names(feat))[1]
  if (is.na(iid)) return(sa)
  tab    <- tapply(as.character(feat[[iid]]), as.character(feat[[gid]]), function(x) length(unique(x)))
  lonely <- names(tab)[tab == 1]
  if (!length(lonely)) return(sa)
  m <- feat[match(lonely, feat[[gid]]), c(gid, iid), drop = FALSE]
  m$fake <- paste0(as.character(m[[iid]]), suffix)
  if (is.data.frame(cnt) && "isoform_id" %in% names(cnt)) {
    ridx <- match(as.character(m[[iid]]), as.character(cnt$isoform_id))
    ok   <- !is.na(ridx)
    add  <- cnt[ridx[ok], , drop = FALSE]
    add$isoform_id <- m$fake[ok]
    sa$isoformCountMatrix <- rbind(cnt, add)
  } else {
    mat  <- as.matrix(cnt)
    ridx <- match(as.character(m[[iid]]), rownames(mat))
    ok   <- !is.na(ridx)
    add  <- mat[ridx[ok], , drop = FALSE]
    rownames(add) <- m$fake[ok]
    sa$isoformCountMatrix <- rbind(mat, add)
  }
  addf <- feat[feat[[gid]] %in% m[[gid]] & feat[[iid]] %in% m[[iid]], , drop = FALSE]
  map  <- setNames(m$fake, as.character(m[[iid]]))
  addf[[iid]] <- unname(map[as.character(addf[[iid]])])
  if ("iso_ref" %in% names(addf)) addf$iso_ref <- paste0(as.character(addf$iso_ref), suffix)
  sa$isoformFeatures <- rbind(feat, addf)
  sa
}
remove_fake_isoforms <- function(sa, suffix = "_fake") {

  feat <- sa$isoformFeatures
  iid  <- intersect(c("isoform_id","transcript_id","isoformId"), names(feat))[1]
  if (is.na(iid)) return(sa)
  pat <- paste0(suffix, "$")
  keep_feat <- !grepl(pat, as.character(feat[[iid]]))
  sa$isoformFeatures <- feat[keep_feat, , drop = FALSE]
  cnt <- sa$isoformCountMatrix
  if (is.data.frame(cnt) && "isoform_id" %in% names(cnt)) {
    keep_cnt <- !grepl(pat, as.character(cnt$isoform_id))
    sa$isoformCountMatrix <- cnt[keep_cnt, , drop = FALSE]
  } else {
    mat <- as.matrix(cnt)
    keep_cnt <- !grepl(pat, rownames(mat))
    sa$isoformCountMatrix <- mat[keep_cnt, , drop = FALSE]
  }
  if (!is.null(sa$isoformRepExpression)) {
    x <- sa$isoformRepExpression
    if (is.data.frame(x) && "isoform_id" %in% names(x)) {
      keep_x <- !grepl(pat, as.character(x$isoform_id))
      sa$isoformRepExpression <- x[keep_x, , drop = FALSE]
    } else {
      mat <- as.matrix(x)
      keep_x <- !grepl(pat, rownames(mat))
      sa$isoformRepExpression <- mat[keep_x, , drop = FALSE]
}}
sa}



if (file.exists(DE_Gene_Significance)){DE_Gene_Significance<-read.table(DE_Gene_Significance,header = TRUE,sep='\t',stringsAsFactors = FALSE,check.names = FALSE)
temp <- match(sa$isoformFeatures$gene_id, DE_Gene_Significance[,1])

# Fill gene_q_value in sa
sa$isoformFeatures$gene_q_value <- as.numeric(DE_Gene_Significance[,2][temp])


}

save.image(paste0("R1_AfterImporteSa_",Name_Study,"_Genes",round(length(unique(sa$isoformFeatures$gene_id))/1000,0)     ,"k_Iso",round(dim(sa)[1]/1000,0),"k.rdata"))



if (Mode == "Global")
{
sa <- preFilter(sa,   IFcutoff = Prefilter_IF_CUTOFF, removeSingleIsoformGenes =FALSE, geneExpressionCutoff  = Prefilter_GENE_EXPR_CUTOFF, isoformExpressionCutoff  = Prefilter_ISOFORM_EXPR_CUTOFF )
sa<-add_fake_isoform_for_single_isoform_genes (sa,"_fake")
if (METHOD=="satuRn"){sa<-isoformSwitchTestSatuRn(sa,reduceFurtherToGenesWithConsequencePotential = FALSE, reduceToSwitchingGenes =FALSE, keepIsoformInAllConditions =TRUE, alpha = Test_Alpha, dIFcutoff = Test_DIF ,diagplots = FALSE,showProgress = TRUE)}   #   Long!! 500k transcripts from 130k genes across 120 samples → 10hours 10GB Ram with home PC       
if (METHOD==  "DEXSeq"){sa<-isoformSwitchTestDEXSeq(sa,reduceFurtherToGenesWithConsequencePotential = FALSE, reduceToSwitchingGenes = FALSE, keepIsoformInAllConditions = TRUE, alpha = Test_Alpha, dIFcutoff = Test_DIF,diagplots = FALSE,showProgress = TRUE)}
 sa <- remove_fake_isoforms(sa, suffix = "_fake")
Name_Study_Detailled<-paste0(Name_Study,"_Global_GeneExp",Prefilter_GENE_EXPR_CUTOFF,"_IsoExp",Prefilter_ISOFORM_EXPR_CUTOFF,"_IF",Prefilter_IF_CUTOFF,"_Genes",round(length(unique(sa$isoformFeatures$gene_id))/1000,0)     ,"k_Iso",round(dim(sa)[1]/1000,0),"k")
}
if(Mode == "Diff")
{
sa <- preFilter(sa,   IFcutoff = Prefilter_IF_CUTOFF, removeSingleIsoformGenes =TRUE, geneExpressionCutoff  = Prefilter_GENE_EXPR_CUTOFF, isoformExpressionCutoff  = Prefilter_ISOFORM_EXPR_CUTOFF )
sa<-add_fake_isoform_for_single_isoform_genes (sa,"_fake")
if (METHOD=="satuRn"){sa<-isoformSwitchTestSatuRn(sa,reduceFurtherToGenesWithConsequencePotential = FALSE, reduceToSwitchingGenes =TRUE, keepIsoformInAllConditions =TRUE, alpha = Test_Alpha, dIFcutoff = Test_DIF ,diagplots = FALSE,showProgress = TRUE)}   #   Long!! 500k transcripts from 130k genes across 120 samples → 10hours 10GB Ram with home PC       
if (METHOD==  "DEXSeq"){sa<-isoformSwitchTestDEXSeq(sa,reduceFurtherToGenesWithConsequencePotential = FALSE, reduceToSwitchingGenes =TRUE, keepIsoformInAllConditions = TRUE, alpha = Test_Alpha, dIFcutoff = Test_DIF,diagplots = FALSE,showProgress = TRUE)}
 sa <- remove_fake_isoforms(sa, suffix = "_fake")
Name_Study_Detailled<-paste0(Name_Study,"_Diff_GeneExp",Prefilter_GENE_EXPR_CUTOFF,"_IsoExp",Prefilter_ISOFORM_EXPR_CUTOFF,"_IF",Prefilter_IF_CUTOFF,"_Alpha",Test_Alpha,"_DIF",Test_DIF,"_Genes",round(length(unique(sa$isoformFeatures$gene_id))/1000,0)     ,"k_Iso",round(dim(sa)[1]/1000,0),"k")
}

if(Mode=="GeneList")
{

GeneList <- read.table(GeneList, header = FALSE, sep = "\t",stringsAsFactors = FALSE)[, 1]
temp<-which(sa$isoformFeatures$gene_id%in% GeneList)
sa$isoformFeatures$gene_biotype[temp]<-"ToKeep"
sa <- preFilter(sa,  acceptedGeneBiotype = "ToKeep", IFcutoff = 0, removeSingleIsoformGenes =FALSE, geneExpressionCutoff  =0, isoformExpressionCutoff  =0,alpha=1,dIFcutoff =0)
sa<-add_fake_isoform_for_single_isoform_genes (sa,"_fake")
if (METHOD=="satuRn"){sa<-isoformSwitchTestSatuRn(sa,reduceFurtherToGenesWithConsequencePotential = FALSE, reduceToSwitchingGenes =FALSE, keepIsoformInAllConditions = TRUE, alpha = Test_Alpha, dIFcutoff = Test_DIF ,diagplots = FALSE,showProgress = TRUE)}   #   Long!! 500k transcripts from 130k genes across 120 samples → 10hours 10GB Ram with home PC     
if (METHOD==  "DEXSeq"){sa<-isoformSwitchTestDEXSeq(sa,reduceFurtherToGenesWithConsequencePotential = FALSE, reduceToSwitchingGenes =FALSE, keepIsoformInAllConditions = TRUE, alpha = Test_Alpha, dIFcutoff = Test_DIF,diagplots = FALSE,showProgress = TRUE)}
 sa <- remove_fake_isoforms(sa, suffix = "_fake")
Name_Study_Detailled<-paste0(Name_Study,"_Genelist_Genes",round(length(unique(sa$isoformFeatures$gene_id))/1000,0)     ,"k_Iso",round(dim(sa)[1]/1000,0),"k")
}

write.table(sa$isoformFeatures,paste0( "IsoformFeatures_",Name_Study_Detailled,".tabtxt"),sep="\t",col.names=NA)

sa <- analyzeORF(sa)
save.image(paste0("R2_AFTERORF_",Name_Study_Detailled,".rdata"))
setwd(SEQ_DIR)

if(Mode=="GeneList"){
sa<-extractSequence(sa, extractNTseq = TRUE, extractAAseq = TRUE, writeToFile = TRUE, onlySwitchingGenes = FALSE,removeShortAAseq =FALSE,removeLongAAseq = FALSE,alpha=1,dIFcutoff =0,addToSwitchAnalyzeRlist=TRUE)
}
if(Mode=="Diff"|Mode=="Global"){
sa<-extractSequence(sa, extractNTseq = TRUE, extractAAseq = TRUE, writeToFile = FALSE, onlySwitchingGenes = FALSE,removeShortAAseq =FALSE,removeLongAAseq = FALSE,alpha=1,dIFcutoff =0,addToSwitchAnalyzeRlist=TRUE)
Temp_Alpha<-unique(c(0.1,0.05,0.01,0.001,Sequence_Alpha,Test_Alpha)) 
Temp_DIF<-unique(c(0.2,0.15,0.1,0.05,Sequence_DIF,Test_DIF)) 

Count_Genes <- matrix(  NA_integer_,   nrow = length(Temp_Alpha),   ncol = length(Temp_DIF),   dimnames = list(     paste0("Alpha_", Temp_Alpha),     paste0("DIF_", Temp_DIF)  ))



for (indice_Alpha in Temp_Alpha) 
{ 
for (indice_DIF in Temp_DIF) 
{
Temp_iso<-which(sa$isoformFeatures$isoform_switch_q_value<=indice_Alpha&abs(sa$isoformFeatures$dIF)>=indice_DIF)
Temp_Gene<-unique(sa$isoformFeatures$gene_id[Temp_iso])
Count_Genes[paste0("Alpha_", indice_Alpha), paste0("DIF_", indice_DIF)] <- length(Temp_Gene)

 Name_Sequence<-paste0("GeneSwitch_",length(Temp_Gene),"_",Name_Study,"_GeneExp",Prefilter_GENE_EXPR_CUTOFF,"_IsoExp",Prefilter_ISOFORM_EXPR_CUTOFF,"_IF",Prefilter_IF_CUTOFF,"_Alpha",indice_Alpha,"_DIF",indice_DIF) 
 extractSequence(sa, extractNTseq = TRUE, extractAAseq = TRUE, writeToFile = TRUE, onlySwitchingGenes = TRUE ,pathToOutput = SEQ_DIR ,removeShortAAseq =FALSE,removeLongAAseq = FALSE,alpha=indice_Alpha,dIFcutoff =indice_DIF,addToSwitchAnalyzeRlist=FALSE,outputPrefix=Name_Sequence) 
 print(paste0(indice_Alpha, "_", indice_DIF, "_", Name_Sequence))
}}
sa<-extractSequence(sa, extractNTseq = TRUE, extractAAseq = TRUE, writeToFile = TRUE, onlySwitchingGenes = FALSE,removeShortAAseq =FALSE,removeLongAAseq = FALSE,alpha=1,dIFcutoff =0,addToSwitchAnalyzeRlist=TRUE)
write.table(Count_Genes,file="GeneSwitchingFctThresolds.tabtxt",sep='\t', col.names = NA)
}

setwd(RUN_DIR)

save.image(paste0("R3_END_Pz3on5_",Name_Study_Detailled,".rdata"))

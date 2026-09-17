

setwd("D:\\Patriot_FastSave\\Biostat\\Microarrays\\Study\\lncRNA Epilepsy\\Estrogen\\Global 2 arrays")
rm(list = ls(all = TRUE))

load("Names_2P_LNCRNA_ProbeName_GeneName_Des.RData")


#region#blue libraries 
library(FactoMineR)
library(gtools)
library(fdrtool)
library(audio)
library(Hmisc)
library(matrixStats)
library(limma)
library(propagate)
library(HiClimR)
library(reshape2)
library(plyr)
library(dplyr)
library(stringr)
library(gplots)
library(NMF)
library(imputeTS)
library(pheatmap)
library(tidyr)
library(imputeTS)
library(naniar)
library(visdat)
library(missMDA)
library(glmnet)


print("OKAY Loaded")


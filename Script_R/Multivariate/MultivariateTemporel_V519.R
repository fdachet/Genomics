#  Date start at 1 not 0
# Put everything upletters
# Input.tabtxt OR InputForValidation.txt
# REMOVE THE NAs before Input???
# Option to keep results across patients only if they are close to each others in a locked time mode
 
# Data needs to not have redundant and no special characters in  

#columns: 1"PATIENT", 2"SCORE_NAME", 3"SCORE_VALUE", 4"SCORE_UNIT", 5"DATE", 6"DATA_TYPE"
#The Score_Name=  COLOR is used to give a color (score_Value) to patients
#Last Column: The Data_type QUALITATIF_NOTEMPOREL  is used for non temporel and qualitatif data , Score_Name = Color, EpilepticStatus
#Last Column: The data_type EMPTYTO0  identify un type d analyzis (e.g. medication acetomiphen)  to fill to 0 for any number value missing

#NEED TO KEEP  LABELS:   CTRL  EP  POS AND PRB   (Else not recognized during graph)


# Need to include NO Temporal Data:  Diagnostic , Epileptic status, medication taken vs no medication, procedures


# Put a score on correlation results based on Epileptic Status (e.g. identification of the correlations enriched in function of Epilepsy)
# in the data_type "Qualitatif_NoTemporel" the data EPILEPTICSTATUS identify the amount of Epilepsy among Epileptic patients (From 1: Epilepsy, to 4: No Epilepsy), more the score is low and more thewre is Epilepsy (Probably to reverse this in the near futur). 01EPILEPSY, 02PROBABLE,EPILEPSY, 03POSSIBLE EPILEPSY, 04NO EPILEPSY. if it is coded 
# IdentifyEpilepsyBias needs 1 for epilepsy and 4 for non epilepsy

# "If a pattern is found is repeated in an other windows, the patient is artificially readded in the weight to give more epileptic weight to show that the pair is really correlated ... (The best is kept)

#Interpolations used are linear (average between 2 points),Stineman: try to correct the exess of the spline interpolation by reducing the splines predicted in case of monotonic series)



# 1) After results use Profils need average of average (1 average intra patient then avera interpatients)
# 2) Separate Negative from Positive correlation by adding column 'Type of correlation' positive or negative
# 3) create column CountOfDays 
# 4) create a fused columne patient_PAirofcorrelation_typeofCorrelation for intrapatient
# 5)  PivotPlot create columns  average correlation, average of days, remove columns correlation and days
# 6) Remove duplicates
# 7) Delete PAtients and fused columns

# 8) create a fused columne PAirofcorrelation_typeofCorrelation for inter_patient analyzis
# 9) PivotPlot create columns  'AverageOfAverage' for average correlation, average of days. Also use the count to create column 'quantityOfPatientsPerPairOfCorrelation
#10) Remove duplicates
#11) Remove columns patients and column Fused

#12) Compute pvalue coulumn in function of days and ABS correl     P==T.DIST.2T(|COR|*SQRT(N-2)/SQRT(1-|COR|^2),N-2)      Correct les "#DIV/0!"

#13) Separate column 'pair of correlation on _Vs_ then Reorder columns for DATA1 Interraction Data2 ...
#
#

rm(list = ls(all = TRUE))


#region#blue libraries 
library(FactoMineR)
library(gtools)
library(fdrtool)
library(audio)
library(Hmisc)
library(matrixStats)
library(ff)
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
library(elasticnet)
library(vioplot)

library(basicPlotteR)   # install.packages("devtools") ; devtools::install_github("JosephCrispell/basicPlotteR")


#endregion#

#region#green Parameters
Multivariate = TRUE
Debug_B <- TRUE     #  put on TRUE to give you more information and identify any potential bug
setwd("P:\\Biostat\\Multivariate\\October\\relaxed\\Mitch_ALL")
MinimumProfilLength <- 7       # For multivariate interractom
MinimumQuantityOfPatientsPerProfil <- 6       # For multivariate interractom
QuantityFirstDaysToRemove = 1 # Quantity of days removed at the begining for complete correlation windows
Correl_Thresold <- 0.7    # For multivariate interractom
DateOrigine <- "2000-1-1"
DateFormat <- FALSE # if dateformat is true transform the date after DateOrigine, else keeps numerical: 1,2,3,4
TimeBining <- 2 # For multivariate interractomQuantity of days to average to create a data point (default = 1)
TimeWindow <- 7 # For multivariate interractomThe quantity of days that the algorithm will use to search correlations inside
TimeShift <- 0 # For multivariate interractomQuantity of day(s) that the script is allowed to shift to find the best correlation  pblm: perd cette duree en jours lors du calcul du profil de corelation  (default = 0)
DataNormalization <- TRUE #   E.c.  Normalize all data inside a type of measurement across days and patients (give the same weight between different types of measurement)   
Nom_Interraction <- ""  # Not used yet
InterractionsMAXExportable <- 500000 # Not used yet
CreateValidationData <- FALSE     #if True need InputForValidation.tabtxt in the wide format (with time as the first row), this create the correct file to be used in excel to creat the final Input.tabtxt (Then put the Epileptic variable for each patient using "Qualitatif_NoTemporel" and the data EPILEPTICSTATUS ) 
SameDayAnalyzis_B = FALSE       # Activate research of correlation around the same day across patients, put DateFormat as FALSE and DataNormalization as TRUE  (default = FALSE)
SameDayDelta = 5     # Not used yet       #only result that have a Delta day spread across the same type of corelation across patients 
PlotData = FALSE  #Plot each analyze in function of patients and time
ExportPatientLabels = FALSE  #Add the information about the name of the patient associated with each results
ScoreInFunctionOfEpilepsy_B = TRUE     #KEEPS ON TRUE !!!!
EMPTYTO0_B= TRUE # Activate le remplissage de 0 pour les valeurs non presentent (uniquement data labeled avec Emptyto0)
IdentifyEpilepsyBias = TRUE  # KEEP ON TRUE!!!!!!!!!!  cancel correlation analyzis do multiple statistic on univariate epilepsy following epileptic code
Code_Non_Epilepsy<-4      #The control non epilepsy have the code 4
Code_Epilepsy<-1     #The epilepsy patients have the code 1
Code_ToPredictEpilepsy <- 0  #The epileptic status of patients with code '0' will be predicited by PCA or LGM or lasso?
PngX= 1920      ;   PngY=1080  # Resolution images (not heatmap)
Heatmap_X=1920     ;    Heatmap_Y=5200  #   1080*1920 2160×3840 resolution in pixels to export images for heatmaps ~300 varaibles  1920×5200 seems good with blocks X34  Y17    policeRow17  policeCol27  maxdays ~31
Color_Ramp <- colorRampPalette(c("blue","white","red"))   #Pour la heatmap     
FontHeatmapRows <- 17 #HEATMAP Taille de la police pour les rows
FontHeatmapCols <- 27 #HEATMAP Taille de la police pour les jours
Heatmap_Font_size_Title <- 30 #HEATMAP Taille de la police pour le titre
Heatmap_ColorMissingData <- "dark grey"
HeatmapBlock_X <- 34  # Largeur en pixel de la heatmap cellule
HeatmapBlock_Y <- 17  # Hauteur en pixel de la heatmap cellule
InfiniteValue=10  # transforme infinite value (coming from division by 0 to 'InfiniteValue' )
#MinimumForBinomialFC<- 1.2 # NOT USED ANYMORE *** (minimal ABS of a median FC or average FC to be compted by binomial search of pattern, for normalized data use 0.2? and non normalized use 1.2)
InfinitePvalue=1e-4 #
PCA_Predictors <- TRUE # Patients without Epilepsy code will be predicted. Force IdentifyEpilepsyBias to TRUE    **** E.C.**** 
InterpoledPrediction_B <- TRUE # If true the predictors use interpoled data with Stineman interpolation
minimun_Q_EpilPatients <- 1      # minimum of epiletic patients for 1 day 1 analyze to be kept  (also need to be higher than 0)
minimun_Q_ControlPatients <- 1    #  minimum of control patients  for 1 day 1 analyze to be kept (also need to be higher than 0)
ABS_FC_Thresold <- 0 # minimum abs fold change for a score to be counted  UP or DOWN (NPO 0 cancel this selection method)
pValue_Thresold <- 0  # minimum pvalue Student score to be counted  UP or DOWN (NPO 0 cancel this selection method)
pValueWilcox_Thresold <- 0.2   # minimum pvalue Wilcox for a score to be counted  UP or DOWN (NPO 0 cancel this selection method)
MinimalDaysSequence <- 1  #  *** The 'BIN' *** Minimal quantity of day creating a repetition inside a sequence of all significant UP or all significant DOWN successive days) that will need to be averaged to create a new data. 
Interpolation_maxgap_inDays <- 10 # the missing measurement will be interpoled inside a maximum of days
Logique = "OR" # if it is "AND" then the selection will be on fold change AND pvalues  NOT USED YET
FractionMaxCreatedForLogicAnalyzis = 0.2  # Fraction of the quantity of patient that can be createdby average using the data of other epileptic patients (needed to remove NA from logistic analyzis)
MinimumQuantityVariablesAnalyzedByGLMNET = 5 # minimum quantity of variables to run the logistic regression 
alpha = 1  # alpha =0 pour ridge   et  1 pour Lasso 
VariablesNeeded<- 40 # Limit the maximum quantity of variables used for prediction

#endregion#

#region#yellow VariablesInternals 
temp=0
if (DataNormalization) {temp=1}
tag<-paste(if(EMPTYTO0_B){"E0_"},if(InterpoledPrediction_B){paste("i",Interpolation_maxgap_inDays,"_",sep="")},"Ep",minimun_Q_EpilPatients,"_Ctrl",minimun_Q_ControlPatients,"_N",temp,"_FC",ABS_FC_Thresold,"_p",pValue_Thresold,"_pW",pValueWilcox_Thresold,"_D",MinimalDaysSequence,sep="","_a",alpha,"_V",VariablesNeeded,"_R",QuantityFirstDaysToRemove)
options(stringsAsFactors = FALSE)
Profils_export_L <- list()
Input_L <- list();temp_L_msd<-list()
Profils_export_Array <- data.frame()
options(stringsAsFactors = FALSE)
if (IdentifyEpilepsyBias) {MinimumProfilLength <- 1;MinimumQuantityOfPatientsPerProfil <- 1 }
if (PCA_Predictors) {IdentifyEpilepsyBias <- TRUE} 
#endregion#

#region#cyan Function1 

Function1 <- function(    Input_Raw   , TimeBining, TimeShift, MinimumProfilLength, MinimumQuantityOfPatientsPerProfil, DateOrigine, Correl_Thresold,window) {
  # CREATE THE INPUT EN LIST , 1 objet pour chaque patient
  temp_Profils_export_L<-list()
  Patients_L <- levels(as.factor(Input_Raw[, 1]))
  Patients_Q <- length(Patients_L)
  Time_delta <- max(Input_Raw[, 4]) - min(Input_Raw[, 4])
  if (Time_delta<MinimumProfilLength){return()}
  Time_min <- min(Input_Raw[, 4])
  #Correl_Thresold_Patients <- critical.r(  Patients_Q, pValue_Thresold)    #Not  used yet!!
  for (i in 1:Patients_Q)
  {
    print(paste("Patient",i,"on",Patients_Q,"for Window#",h))
    temp <- which(Input_Raw[, 1] == Patients_L[i])
    Input_L[[i]] <- Input_Raw[temp, ]
    Input_L[[i]] <- Input_L[[i]][, -1]
    Input_L[[i]][, 3] <- as.numeric(Input_L[[i]][, 3])
    temp <- max(Input_L[[i]][, 3])
    temp1 <- array(NA, c(Time_delta+1, length(levels(as.factor(Input_L[[i]][, 1]))) + 1))
    temp1[, 1] <-  Time_min:(Time_min+(Time_delta))
    colnames(temp1) <- c("DATE", levels(as.factor(Input_L[[i]][, 1])))
    temp1 <- as.data.frame(temp1)
    Input_L[[i]] <- cbind(temp1[1], sapply(names(temp1)[-1], function(X) subset(Input_L[[i]], SCORE_NAME == X)$SCORE_VALUE[match(temp1$DATE, subset(Input_L[[i]], SCORE_NAME == X)$DATE)]))
    
  }
  
  #endregion#
  
  #region#cyan function1: TimeShift: ADD COLUMN POUR LES DATES EN DEPHASEES
  if (TimeShift != 0) {
    print("Compute Time Shift")
    TimeShift <- abs(TimeShift)
    for (i in 1:Patients_Q)
    {
      print(paste("Computing Time Shifts for Patient",i,"on",Patients_Q))
      temp <- Input_L[[i]]
      temp1 <- colnames(temp)[-1]
      temp <- as.matrix(temp[, -1])
      
      for (j in 1:TimeShift)
      {
        if (!SameDayAnalyzis_B){colnames(temp) <- paste(temp1, "_Delta+", j, sep = "")}
        temp <- rbind(temp[1, ], temp)
        temp[1, ] <- NA
        Input_L[[i]] <- rbind(Input_L[[i]], Input_L[[i]][1, ])
        Input_L[[i]][dim(Input_L[[i]])[1], ] <- NA
        Input_L[[i]] <- cbind(Input_L[[i]], temp)
        temp2<-dim(Input_L[[i]])[1]            #ADDED  E.C
        Input_L[[i]][temp2,1]<-1+ Input_L[[i]][temp2-1,1]               #ADDED  E.C
      }
    }    }
  
  #endregion#
  
  
  #region#cyan function1:  TimeBining: Bin les dates par aglomeration
  if (TimeBining > 1) {
    for (i in 1:Patients_Q)
    {
      print(paste("Binning Dates for Patient",i,"on",Patients_Q))
      temp <- cut(Input_L[[i]][, 1], breaks = seq(from = min(Input_L[[i]][, 1]) - 1, to = max(Input_L[[i]][, 1]), by = TimeBining))
      Input_L[[i]] <- cbind(temp, Input_L[[i]])
      Input_L[[i]] <- aggregate(Input_L[[i]], by = list(Input_L[[i]][, 1]), FUN = mean, na.rm = TRUE)
      Input_L[[i]] <- cbind(ceil(Input_L[[i]][, 3]), Input_L[[i]])
      Input_L[[i]] <- Input_L[[i]][, -c(2:4)]
      colnames(Input_L[[i]])[1] <- "DATE"
    }    }
  names(Input_L) <- Patients_L
  #endregion#
  
  #region#cyan function1:     # COMPUTE CORRELATIONS, filtre, enleve dates, maximal in case of timeshift dephasage...
  Input_L_Cor <- lapply(Input_L, function(X) {   cor(X, use = "pairwise")    })
  for (i in 1:Patients_Q)
  {
    # FILTRE LES CORRELATIONS , ENLEVE LES NON-RELEVANTES, ENLEVE DATE
    print(paste("Filter Correlations for Patient",i,"on",Patients_Q))
    
    Input_L_Cor[[i]] <- Input_L_Cor[[i]][-1, -1]
    temp<-dim(Input_L_Cor[[i]])[2]
    if (!is.null(temp)&&temp>TimeShift)
    {
      
      
      temp_VariableQ <- (temp) / (TimeShift + 1)
      Input_L_Cor[[i]][lower.tri(Input_L_Cor[[i]], diag = TRUE)] <- NA
      Input_L_Cor[[i]][which(abs(Input_L_Cor[[i]]) < Correl_Thresold)] <- NA
      temp_colnames <- colnames(Input_L_Cor[[i]])
      # TAKE ONLY THE MAXIMAL CORRELATION IN CASE OF MULTIPLE CORRELATION FOR DEPHASAGES
      if (TimeShift != 0) {
        temp_k <- t(kronecker(matrix(1:((1+TimeShift)^2),TimeShift+1,byrow=FALSE),matrix(1,temp_VariableQ,temp_VariableQ)))
        temp <- split(Input_L_Cor[[i]], temp_k)
        #      temp <- array(unlist(temp), c(temp_VariableQ* (TimeShift + 1),temp_VariableQ* (TimeShift + 1), TimeShift + 1))
        temp<-array(unlist(temp),c(temp_VariableQ,temp_VariableQ,(1+TimeShift)^2))
        
        if (dim(temp)[1]>=2)
        {
          for (j in 1:((TimeShift + 1)^2))
          {
            diag(temp[, , j]) <- NA
          }
        }
        temp <- aperm(temp, c(3, 2, 1))
        temp <- apply(temp, c(2, 3), function(Y) {Y[-which.max(abs(Y))] <- NA;Y})
        temp <- aperm(temp, c(3, 2, 1))
        #   temp <- array(temp, c(temp_VariableQ * (TimeShift + 1), temp_VariableQ * (TimeShift + 1))) 
        temp<-split(as.numeric(temp),ceiling(seq_along(temp)/temp_VariableQ^2))
        temp<-matrix(unsplit(temp,temp_k),c(temp_VariableQ * (TimeShift + 1), temp_VariableQ * (TimeShift + 1)))
        colnames(temp) <- temp_colnames
        rownames(temp) <- temp_colnames
        temp <- round(temp, 2)
        Input_L_Cor[[i]] <- temp    
      }
      #endregion#
      #region#cyan function1:  EXPORT LES PROFILES
      temp_notNA <- which(!is.na(Input_L_Cor[[i]]), arr.ind = TRUE)
      for (j in 1:dim(temp_notNA)[1])
      {
        if (length(temp_notNA) != 0) {
          temp1 <- Input_L[[i]][, 1 + temp_notNA[j, 1]]
          temp2 <- Input_L[[i]][, 1 + temp_notNA[j, 2]]
          temp3 <- !is.na(temp1) & !is.na(temp2)
          temp1 <- temp1[temp3]
          temp2 <- temp2[temp3]
          if (length(temp1) >= MinimumProfilLength) {
            temp3 <- which(temp3)
            temp_cor <- Input_L_Cor[[i]][temp_notNA[j, 1], temp_notNA[j, 2]]
            temp <- sort(c(temp_colnames[temp_notNA[j, 1]], temp_colnames[temp_notNA[j, 2]]))
            temp_pairName <- paste(temp[1], "_Vs_", temp[2], sep = "")
            temp1 <- c(paste("window=",window,sep=""),Patients_L[i], temp_pairName, temp[1], temp_cor, temp[2], paste(temp_colnames[temp_notNA[j, 1]], "="), temp1)
            temp2 <- c(paste("window=",window,sep=""),Patients_L[i], temp_pairName, temp[1], temp_cor, temp[2], paste(temp_colnames[temp_notNA[j, 2]], "="), temp2)
            if(DateFormat&&!SameDayAnalyzis_B){  temp3 <- c(Patients_L[i], temp_pairName, temp[1], temp_cor, temp[2], "Date=", as.character(as.Date(DateOrigine) + (Time_min +as.numeric(TimeBining * temp3))))}
            if(!DateFormat||SameDayAnalyzis_B){  temp3 <- c(Patients_L[i], temp_pairName, temp[1], temp_cor, temp[2], "Date=",  (Time_min +as.numeric(TimeBining * temp3)-1))  }    
            
            temp3<-c(paste("window=",window,sep=""),temp3)
            
            temp4 <- rbind(temp3, temp2, temp1)
            temp_Profils_export_L[[length(temp_Profils_export_L) + 1]] <- temp4
          }
        }
      }
    }
  }
  return(temp_Profils_export_L)
  
}



Function_HeatMap <- function(X,title)
{
  
  temp<-gsub("_Array","",deparse(substitute(X)))
 
  if (DataNormalization)   {temp<-paste(temp,"_NORMALIZED",sep="")}
  
  png(paste(temp,".png",sep=""), width=Heatmap_X, height=Heatmap_Y, units="px")
  pheatmap( X ,cluster_rows = FALSE, color =  clrs, show_colnames= TRUE,cluster_cols = FALSE,annotation_names_col = FALSE,scale="none",main=paste(temp,"_",title,sep=""),breaks = breaks,   fontsize_row=FontHeatmapRows,fontsize_col=FontHeatmapCols,show_rownames= TRUE,angle_col=0, cellwidth=HeatmapBlock_X, cellheight=HeatmapBlock_Y, fontsize=Heatmap_Font_size_Title , na_col=Heatmap_ColorMissingData )
  dev.off()
  
}




PCA_To_File_F <- function (X,temp_title)
{

png (paste("R_PCA_Ind_",temp_title,"_Ep",length(Row_Epilepsy),"_Ctrl",length(Row_Control),'_',tag,".png"),width =1920,height =1080,units = "px",)
plot(plot(X,choix="ind",habillage=1,axes=c(1,2),label="none",title=temp_title,col.hab=c("blue","red","green"),cex=2))
dev.off()
png (paste("R_PCA_Ind_Labels",temp_title,"_Ep",length(Row_Epilepsy),"_Ctrl",length(Row_Control),'_',tag,".png"),width =1920,height =1080,units = "px",)
plot(plot(X,choix="ind",habillage=1,axes=c(1,2),title=temp_title,col.hab=c("blue","red","green"),cex=1))
dev.off()
png (paste("R_PCA_Var_",temp_title,"_Ep",length(Row_Epilepsy),"_Ctrl",length(Row_Control),'_',tag,".png"),width =1920,height =1080,units = "px",)
plot(plot(X,choix="var",axes=c(1,2),title=temp_title))
dev.off()
}



#endregion#-------------------

##############################  START   #############################



#region#black Create ValidationData for testing       WHAT ABOUT USING OF   reshape insetad of melt/caste?
if (CreateValidationData){
  Input_L_Raw <- read.table("InputForValidation.txt", sep = "\t", header = FALSE, check.names = FALSE)
  Input_L_Raw[,1]<-paste(Input_L_Raw[,1],Input_L_Raw[,2],sep="@_@")
  Input_L_Raw<-apply(Input_L_Raw,2,toupper)
  rownames(Input_L_Raw)<-Input_L_Raw[,1]
  Input_L_Raw<-Input_L_Raw[,-c(1:2)]
  Input_L_Raw<-t(Input_L_Raw )
  Input_L_Raw<-as.data.frame(Input_L_Raw)
  b_m<-melt(Input_L_Raw,id.vars="DATE@_@DATE")
  b_m<-b_m[,c(2,2,3,1,1)]
  b_m[,4]<-"Unknown"
  b_m<-rbind(b_m[1,],b_m)
  b_m<-apply(b_m,2,as.character)
  b_m[1,]<-c("PATIENT", "SCORE", "SCORE_VALUE", "SCORE_UNIT", "DATE")
  b_m[,1]<-sub(pattern="@_@.*",   replacement="",x=b_m[,1])
  b_m[,2]<-sub(pattern=".*@_@",   replacement="",x=b_m[,2])
  b_m<-cbind(b_m,"DATA_TYPE")
  
  
  
  
  if (Debug_B){write.table(b_m,file="Input.tabtxt",sep="\t",col.names = FALSE,row.names = FALSE)}
  
  
  
  stop("***** Validation Data created ******")
}
#endregion#--------------




#region#yellow
print("START")

Input_L_Raw <- read.table("Input.tabtxt", sep = "\t", header = FALSE, check.names = FALSE)
Input_L_Raw<-apply(Input_L_Raw,2,toupper)
Directory_Root<-getwd()
 dir.create(tag)
  setwd(paste(Directory_Root,"/",tag,sep=""))
Directory_Root<-getwd()

#endregion#

#region#green
# Verify units are all the same for each score_Name, cancel everything if not the same units. Remove Units if they are okay
# LOOSELY IMPLEMENTED
colnames(Input_L_Raw) <- c("PATIENT", "SCORE_NAME", "SCORE_VALUE", "SCORE_UNIT", "DATE","Data Type")
print("Verify Adequation")
print(Input_L_Raw[1, ])
Input_L_Raw <- Input_L_Raw[-1, ]


# Separate Qualitatif from Quantitative
temp<-which(Input_L_Raw[,6]=="QUALITATIF_NOTEMPOREL")
Input_L_Raw_Qualitatif<-Input_L_Raw[temp,]
if (length(temp) !=0) {Input_L_Raw<-Input_L_Raw[-temp,]}
Input_L_Raw_Qualitatif<-as.data.frame(Input_L_Raw_Qualitatif)



Input_L_Raw <- as.data.frame(Input_L_Raw )
Input_L_Raw [,3]<-as.numeric(Input_L_Raw [,3])
Input_L_Raw [,5]<-as.numeric(Input_L_Raw [,5])




#endregion#

#region#red    Remove first days for total windows correlation
print("QuantityFirstDaysToRemove")
if (QuantityFirstDaysToRemove!=0)
{

for (indice in 1:QuantityFirstDaysToRemove)

{
temp<-which(Input_L_Raw[,5]==indice)

Input_L_Raw<-Input_L_Raw[-temp,]



}
}


#endregion#
#region#lightblue  Remove si pas assez de data points per patients per analyzis----
print("Remove si pas assez de data points per patients per analyzis")
Input_L_Raw<-cbind(Input_L_Raw,paste(Input_L_Raw[,1],Input_L_Raw[,2]))

temp<- ave(Input_L_Raw[,ncol(Input_L_Raw)],Input_L_Raw[,ncol(Input_L_Raw)], FUN=length)

Input_L_Raw<-cbind(Input_L_Raw,temp)
Input_L_Raw[,ncol(Input_L_Raw)]<-as.numeric(Input_L_Raw[,ncol(Input_L_Raw)])
temp<-which(Input_L_Raw[,ncol(Input_L_Raw)]<MinimumProfilLength)

print(paste("Removing",length(temp),"data with less than",MinimumProfilLength,"Points", "from total of",dim(Input_L_Raw)[1] ) )



if(length(temp)!=0){Input_L_Raw<-Input_L_Raw[-temp,]}
Input_L_Raw<-Input_L_Raw[,-ncol(Input_L_Raw)]
Input_L_Raw<-Input_L_Raw[,-ncol(Input_L_Raw)]
#endregion#


#region#green #creer EmptyTo0_Scores_L
EmptyTo0_Scores_L<-NA
if(EMPTYTO0_B)
{
  print("FilledTo0 Started")
 EmptyTo0_Scores_L<-Input_L_Raw[which(Input_L_Raw[,6]=="EMPTYTO0"),2]   
  if (length (EmptyTo0_Scores_L) >=1 ){Input_L_Raw<-Input_L_Raw[-which(Input_L_Raw[,6]=="EMPTYTO0"),] }
}
if(!EMPTYTO0_B)
{
    print("EmptyTo0 not activated, CleaningEmptyTo0 ")
  temp<-which(Input_L_Raw[,6]=="EMPTYTO0")
  if (length (temp) >=1 ){Input_L_Raw<-Input_L_Raw[-temp,]}
}

print("Input list to Input Array")
Max_Days<-max(Input_L_Raw[,5],na.rm = T)
temp<-Input_L_Raw[,-6];temp<-temp[,-4]
temp1<-cbind(array(NA,c(Max_Days,3)),(1:Max_Days))
colnames(temp1)<-colnames(temp)
temp<-rbind(temp,temp1)

Input_A<-as.data.frame(complete(temp,PATIENT,SCORE_NAME,DATE))

Input_A<-Input_A[-which(is.na(Input_A[,1])),]
Input_A<-Input_A[-which(is.na(Input_A[,2])),]
print("Reshaping....")
Input_A<-reshape(Input_A,direction='wide',idvar=c("PATIENT","SCORE_NAME"),timevar="DATE")
Input_A<-Input_A[order(Input_A[,2],Input_A[,1]),]

if (Debug_B){write.table(Input_A,"R_InputArrayOriginal.tabtxt",col.names=TRUE,row.names=FALSE,sep="\t")}

RowEmptyTo0<-which(Input_A[,2]  %in% EmptyTo0_Scores_L)    # EMPTYTO0_B
if (length(RowEmptyTo0)>0){Input_A[RowEmptyTo0,]<-apply(Input_A[RowEmptyTo0,],2,function(X){temp<-which(is.na(X));X[temp]<-0;return(X)})}
if (Debug_B){write.table(Input_A,"R_InputArray_EmptyTo0.tabtxt",col.names=TRUE,row.names=FALSE,sep="\t")}

colnames(Input_A)<-gsub(colnames(Input_A),pattern="SCORE_VALUE.",replace="")
temp<-Input_A[,-c(1:2)]
temp<-temp[,order(as.numeric(colnames(temp)))]
colnames(temp)<-paste("Day_",colnames(temp),sep="")


if(InterpoledPrediction_B)
{
  print(paste("Interpolation Activated Maxgap=",Interpolation_maxgap_inDays,"day(s)"))
temp<-apply(temp,2,as.numeric)
#temp<-  t(as.data.frame(apply(temp,1,function(X) {   tryCatch ( {na_interpolation(X,maxgap=Interpolation_maxgap_inDays,option="stine")}, error=function(e) {NA} )}))) # PROBLEM IF only 1 data → replaced by NA

temp<-  t(as.data.frame(apply(temp,1,function(X) { if (sum(!is.na(X))>=2)  {  X<-na_interpolation(X,maxgap=Interpolation_maxgap_inDays,option="stine")};return(X)   } )))



Input_A<-cbind(Input_A[,c(1:2)],temp)
}
Input_A<-rbind(colnames(Input_A),Input_A)
if (Debug_B){write.table(Input_A,paste("R_InputArray_EmptyTo0_Interpoled",Interpolation_maxgap_inDays,"days.tabtxt"),col.names=FALSE,row.names=FALSE,sep="\t")}
Input_A<-Input_A[-1,]
rownames(Input_A)<-NULL
Input_A_header<-Input_A[,c(1:2)]
Input_A_numerics<-apply(Input_A[,-c(1:2)],2,as.numeric)


 Score_L <- levels(as.factor(Input_A_header[, 2]))
  Score_Q <- length(Score_L)

 Patients_L <- levels(as.factor(Input_A_header[, 1]))
  Patients_Q <- length(Patients_L)

Days_L <- 1:Max_Days
Days_Q <- Max_Days



#endregion#




#region#blue merge analyze with units, remove units    *Le truc qui sert a rien *
Input_L_Raw <- Input_L_Raw[, -4]
levels_factors<- Score_L

#endregion#



#region#cyan  Plot original data-------
#if (PatientColorsAdded) {PatientsColor<-Input_L_Raw[-1,c(1,6)];Input_L_Raw<-Input_L_Raw[,-6]}
if (PlotData)
{
   dir.create("R_PlotOriginalData")
  setwd(paste(Directory_Root,"/R_PlotOriginalData",sep=""))

  print("PlotOriginalData")
  FactorLevels<-levels(as.factor(Input_L_Raw[,2]))
  for (factor_indice in 1:length(FactorLevels))
  {
    
    temp1<-Input_L_Raw[which(Input_L_Raw[,2]==FactorLevels[factor_indice]),]      
    temp1<-temp1[order(temp1[,1],temp1[,4]),]
    temp<- c(grep("PRB",temp1[,1]),grep("POS",temp1,1))
    if (length(temp)>=1) {    temp1<-temp1[-temp,]}
    

    temp_Y_min<-min(temp1[,3],na.rm = TRUE)
    temp_Y_max<-max(temp1[,3],na.rm = TRUE)
    temp_X_min<-min(temp1[,4],na.rm = TRUE)
    temp_X_max<-max(temp1[,4],na.rm = TRUE)
    temp_dataType<-temp1[1,5]
    
    temp_patientLevels<-levels(as.factor(temp1[,1]))
    
    
    if (length(temp_patientLevels) < MinimumQuantityOfPatientsPerProfil){next}
    temp_title<-paste(FactorLevels[factor_indice],"_(",temp_dataType,")_",length(temp_patientLevels),"pts_Original",sep="") 

    temp_patientColorsLine<-rep("Grey",length(temp_patientLevels))
    temp<-grep("CTRL",temp_patientLevels)
    temp_patientColorsLine[temp]<-"Blue"
    temp<-grep("EP",temp_patientLevels)
    temp_patientColorsLine[temp]<-"Red"

    temp_patientColorsPoints<-rep("Grey",length(temp_patientLevels))
    temp<-grep("CTRL",temp_patientLevels)
    temp_patientColorsPoints[temp]<-"Blue"
    temp<-grep("EP",temp_patientLevels)
    temp_patientColorsPoints[temp]<-"Red"




    png(filename=paste("R_",FactorLevels[factor_indice],"_Original.png",sep=""),width=1920, height=1080,units="px",)
    
    for (patient_indice in 1:length(temp_patientLevels))
    {
      #print(paste("Plotting of",FactorLevels[factor_indice],"for patient:",temp_patientLevels[patient_indice]))
      if (temp_patientColorsPoints[patient_indice]!="Grey")
      {
      temp2<-temp1[which(temp1[,1]==temp_patientLevels[patient_indice]),]      
      
      par(new=TRUE)
      
      #temp_title<-paste(FactorLevels[factor_indice],"_(",temp_dataType,")_",length(temp_patientLevels),"pts",sep="")
   temp_color<-temp_patientColorsPoints[patient_indice]
      #if (PatientColorsAdded) {temp_color<-temp2[,5]}
      noiseY = rep((temp_Y_max-temp_Y_min)/50,length(temp2[,3]))-runif(length(temp2[,3]),0,2*(temp_Y_max-temp_Y_min))/50
      #noiseX = rep((temp_X_max-temp_X_min)/50,length(temp2[,4]))-runif(length(temp2[,4]),0,2*(temp_X_max-temp_X_min))/50
      noiseX=0
      temp2[,3]<-temp2[,3]+noiseY
      temp2[,4]<-temp2[,4]+noiseX
      plot(x=temp2[,4] ,    y=temp2[,3], main=temp_title, ylim=c(temp_Y_min, ymax=temp_Y_max),xlim=c(temp_X_min, temp_X_max), xlab="Date",ylab="Value" ,type='p',col=temp_color,pch = 19 )
      
   

      temp_color<-temp_patientColorsLine[patient_indice]
        #if (PatientColorsAdded) {temp_color<-temp2[,5]}
      
      par(new=TRUE)
      lines(x=temp2[,4] ,    y=temp2[,3], col=temp_color,lwd =3)
      
      
      }
    }
    dev.off()
    par(new=FALSE)
    
  }

  #if (PatientColorsAdded) {Input_L_Raw<-Input_L_Raw[,-5]}
  #png(filename=paste(temp_pairs_levels[pair_i],".png"),width=1920, height=1080,units="px",)
  #dev.off()

Input_L_Raw<-Input_L_Raw[,-ncol(Input_L_Raw)]
setwd(Directory_Root)
#endregion#



#region#yellow  Plot interpoled data-------
 print("PlotInterpoledData_CTRL&EPIL")
 dir.create("R_PlotInterpoledData")
  setwd(paste(Directory_Root,"/R_PlotInterpoledData",sep=""))
FactorLevels<-levels(as.factor(Input_A[,2]))
  for (factor_indice in 1:length(FactorLevels))
  {
    
    temp1<-Input_A[which(Input_A[,2]==FactorLevels[factor_indice]),]      
    temp1<-temp1[order(temp1[,1]),]
temp<-c(grep("POS",temp1[,1]),grep("PRB",temp1[,1]))
temp1<-temp1[-temp,]
temp1_N <-apply(temp1[,3:ncol(temp1)],2,as.numeric)
temp1[,3:ncol(temp1)]<-temp1_N
    temp_Y_min<-min(temp1_N,na.rm = TRUE)
    temp_Y_max<-max(temp1_N,na.rm = TRUE)
    if (is.infinite(temp_Y_min)||is.infinite(temp_Y_max)){next}
    temp_X_min<-1
    temp_X_max<-Max_Days
       temp_patientLevels<-levels(as.factor(temp1[,1]))
        if (length(temp_patientLevels) < MinimumQuantityOfPatientsPerProfil){next}
    temp_title<-paste(FactorLevels[factor_indice],"_",length(temp_patientLevels),"pts_Interpoled",sep="") 
    temp_patientColorsLine<-rep("Grey",length(temp_patientLevels))
    temp<-grep("CTRL",temp_patientLevels)
    temp_patientColorsLine[temp]<-"Blue"
    temp<-grep("EP",temp_patientLevels)
    temp_patientColorsLine[temp]<-"Red"

    temp_patientColorsPoints<-rep("Grey",length(temp_patientLevels))
    temp<-grep("CTRL",temp_patientLevels)
    temp_patientColorsPoints[temp]<-"Blue"
    temp<-grep("EP",temp_patientLevels)
    temp_patientColorsPoints[temp]<-"Red"

    png(filename=paste("R_",FactorLevels[factor_indice],"_Interpoled.png",sep=""),width=1920, height=1080,units="px",)
    
    for (patient_indice in 1:length(temp_patientLevels))
    {
        if (temp_patientColorsPoints[patient_indice]!="Grey")
      {
      temp2<-temp1_N[patient_indice,]      
      
      par(new=TRUE)
      
    
   temp_color<-temp_patientColorsPoints[patient_indice]
     
      noiseY = rep((temp_Y_max-temp_Y_min)/50,Max_Days)-runif(Max_Days,0,2*(temp_Y_max-temp_Y_min))/50
      #noiseX = rep((Max_Days)/50,Max_Days)-runif(Max_Days,0,2*Max_Days)/50
      noiseX=0
      temp2_Y<-temp2+noiseY
      temp2_X<-seq(1:Max_Days)+noiseX
      plot(x=temp2_X ,    y=temp2_Y, main=paste(temp_title,"_CTRL&EPIL",paste=""), ylim=c(temp_Y_min, ymax=temp_Y_max),xlim=c(temp_X_min, temp_X_max), xlab="Date",ylab="Value" ,type='p',col=temp_color,pch = 19 )
      
   

      temp_color<-temp_patientColorsLine[patient_indice]
        #if (PatientColorsAdded) {temp_color<-temp2[,5]}
      
      par(new=TRUE)
      lines(x=temp2_X ,    y=temp2_Y, col=temp_color,lwd =3)
      
      
      }
    }
    dev.off()
    par(new=FALSE)



    png(filename=paste("R_",FactorLevels[factor_indice],"_Interpoled_Ctrl.png",sep=""),width=1920, height=1080,units="px",)
    
    for (patient_indice in 1:length(temp_patientLevels))
    {
  
      if (temp_patientColorsPoints[patient_indice]=="Blue")
      {
      temp2<-temp1_N[patient_indice,]      
      
      par(new=TRUE)
      
    
   temp_color<-temp_patientColorsPoints[patient_indice]
     
      noiseY = rep((temp_Y_max-temp_Y_min)/50,Max_Days)-runif(Max_Days,0,2*(temp_Y_max-temp_Y_min))/50
      #noiseX = rep((Max_Days)/50,Max_Days)-runif(Max_Days,0,2*Max_Days)/50
     # noiseX=0
      temp2_Y<-temp2+noiseY
      temp2_X<-seq(1:Max_Days)+noiseX
      plot(x=temp2_X ,    y=temp2_Y, main=paste(temp_title,"_Controls",sep=""), ylim=c(temp_Y_min, ymax=temp_Y_max),xlim=c(temp_X_min, temp_X_max), xlab="Date",ylab="Value" ,type='p',col=temp_color,pch = 19 )
      
   

      temp_color<-temp_patientColorsLine[patient_indice]
        #if (PatientColorsAdded) {temp_color<-temp2[,5]}
      
      par(new=TRUE)
      lines(x=temp2_X ,    y=temp2_Y, col=temp_color,lwd =3)
      
      
      }
    }
    dev.off()
    par(new=FALSE)


    png(filename=paste("R_",FactorLevels[factor_indice],"_Interpoled_Epil.png",sep=""),width=1920, height=1080,units="px",)
    
    for (patient_indice in 1:length(temp_patientLevels))
    {
  
      if (temp_patientColorsPoints[patient_indice]=="Red")
      {
      temp2<-temp1_N[patient_indice,]      
      
      par(new=TRUE)
      
    
   temp_color<-temp_patientColorsPoints[patient_indice]
     
      noiseY = rep((temp_Y_max-temp_Y_min)/50,Max_Days)-runif(Max_Days,0,2*(temp_Y_max-temp_Y_min))/50
      #noiseX = rep((Max_Days)/50,Max_Days)-runif(Max_Days,0,2*Max_Days)/50
     # noiseX=0
      temp2_Y<-temp2+noiseY
      temp2_X<-seq(1:Max_Days)+noiseX
      plot(x=temp2_X ,    y=temp2_Y, main=paste(temp_title,"_Epileptics",sep=""), ylim=c(temp_Y_min, ymax=temp_Y_max),xlim=c(temp_X_min, temp_X_max), xlab="Date",ylab="Value" ,type='p',col=temp_color,pch = 19 )
      
   

      temp_color<-temp_patientColorsLine[patient_indice]
        #if (PatientColorsAdded) {temp_color<-temp2[,5]}
      
      par(new=TRUE)
      lines(x=temp2_X ,    y=temp2_Y, col=temp_color,lwd =3)
      
      
      }
    }
    dev.off()
    par(new=FALSE)
  }
}
  print("Debug")
  setwd(Directory_Root)

#endregion#

#region#lightgreen IdentifyEpilepsyBias

if (IdentifyEpilepsyBias) {
  
  print ("IdentifyEpilepsyBias")

  temp<-matrix(NA,nrow=Score_Q,ncol=Days_Q)
  pValue_Array<-temp
  pValueWilcox_Array<-temp

  Averages_Array<-temp
  Averages_Array_KeepBino<-temp
  pValue_Array_KeepBino<-temp
    pValueWilcox_Array_KeepBino<-temp


 temp <- Input_A_header[which(Input_A_header[,2] == Score_L[1]),]
Input_L_Raw_Qualitatif <- Input_L_Raw_Qualitatif[!duplicated(Input_L_Raw_Qualitatif), ]
 Row_Epilepsy<-c(  Input_L_Raw_Qualitatif[,1][ which(Input_L_Raw_Qualitatif[,3]==Code_Epilepsy)])
    Row_Epilepsy<-which((temp[,1]) %in% Row_Epilepsy)
     Row_Control<-c(  Input_L_Raw_Qualitatif[,1][ which(Input_L_Raw_Qualitatif[,3]==Code_Non_Epilepsy)])
    Row_Control<-which((temp[,1]) %in% Row_Control)
     Row_EpilepsyToPredict<-c(  Input_L_Raw_Qualitatif[,1][ which(Input_L_Raw_Qualitatif[,3]==Code_ToPredictEpilepsy)])
    Row_EpilepsyToPredict<-which((temp[,1]) %in% Row_EpilepsyToPredict)



  for (Indice_Score in 1:Score_Q)        #**********************************************************START LOOP  Indice_Score
  {
    print(paste(Score_L[Indice_Score],", Score",Indice_Score,"on",Score_Q))
    temp <- which(Input_A_header[,2] == Score_L[Indice_Score])
    Input_EnCours<-Input_A_numerics[temp,]
    
    temp_More0_QEp_patients<-apply(Input_EnCours[Row_Epilepsy,],2,function(X){     sum(abs(X)>0,na.rm=TRUE)})
    temp_More0_QControl_patients<-apply(Input_EnCours[Row_Control,],2,function(X){     sum(abs(X)>0,na.rm=TRUE)})

    # Means
    if ((ABS_FC_Thresold)!=0)
    {
    temp1<-  apply(Input_EnCours,2,function(X){ temp<-(mean(X[Row_Epilepsy],na.rm = TRUE) / mean(X[Row_Control],na.rm = TRUE));temp[temp<1] <-  -1/temp[temp<1] ;     return(temp)})
    temp1[which((temp_More0_QEp_patients==0)&(temp_More0_QControl_patients!=0))]<- -InfiniteValue
    temp1[which((temp_More0_QEp_patients!=0)&(temp_More0_QControl_patients==0))]<-  InfiniteValue
    if(all(is.na(temp_More0_QControl_patients))){temp_More0_QControl_patients<-0}
        if(all(is.na(temp_More0_QEp_patients))){temp_More0_QEp_patients<-0}

    #temp1[which((temp1>1)&(temp_More0_QEp_patients<minimun_Q_EpilPatients))] <- NA   # old logic allowed low number of epileptic patients when downregulated
    #temp1[which((temp1<1)&(temp_More0_QControl_patients<minimun_Q_ControlPatients))] <- NA 
    temp1[which((temp_More0_QEp_patients<minimun_Q_EpilPatients)&(temp_More0_QControl_patients<minimun_Q_ControlPatients))] <- NA  # new logic the thresold on the quantity of patients is not relevant of the orientation of the regulation
     Averages_Array[Indice_Score,]<- temp1
    }
    #pvalue normal
    if ((pValue_Thresold)!=0)
    {
    temp1<-apply(Input_EnCours,2,function(X){tryCatch ( {t.test(X[Row_Epilepsy],X[Row_Control],var.equal=TRUE)$p.value }, error=function(e) {NA}  )  })
    temp1[which((is.na(temp1))&(temp_More0_QEp_patients!=temp_More0_QControl_patients))]<- InfinitePvalue
    temp1[which((temp_More0_QEp_patients<minimun_Q_EpilPatients)&(temp_More0_QControl_patients<minimun_Q_ControlPatients))] <- NA 
    pValue_Array[Indice_Score,]<- temp1
    }
    #pvalue Wilcox
      if ((pValueWilcox_Thresold)!=0)
    {
      
 temp1<-apply(Input_EnCours,2,function(X){tryCatch ( {wilcox.test(X[Row_Epilepsy],X[Row_Control])$p.value }, error=function(e) {NA}  )  })
 temp1[which((is.na(temp1))&(temp_More0_QEp_patients!=temp_More0_QControl_patients))]<- InfinitePvalue
  temp1[which((temp_More0_QEp_patients<minimun_Q_EpilPatients)&(temp_More0_QControl_patients<minimun_Q_ControlPatients))] <- NA 
  pValueWilcox_Array[Indice_Score,]<- temp1
    }
    #endregion#
    


}    #**********************************************************  END LOOP  Indice_Score



        print("Debug")

#region#cyan

  #Print les heatmaps EN COURS NON FILTERED
  dir.create("R_HeatMaps_NotFiltered")
  setwd(paste(Directory_Root,"/R_HeatMaps_NotFiltered",sep=""))

   row.names(pValue_Array)<-levels_factors
  row.names(pValueWilcox_Array)<-levels_factors
  row.names(Averages_Array)<-levels_factors
  colnames(pValue_Array)<-1:Days_Q
  colnames(pValueWilcox_Array)<-1:Days_Q
  colnames(Averages_Array)<-1:Days_Q

     #Heatmaps pValues
     
   if (pValue_Thresold!=0){
   clrs <- rev(Color_Ramp(30))
  breaks<-seq(0.0001, 0.01, length.out = 10)
  breaks<-c(breaks,seq(0.011,0.2,length.out = 10))
  breaks<-c(breaks,seq(0.21,0.4,length.out = 10))
   Function_HeatMap(pValue_Array,"Raw")
   }
#Heatmaps pValuesWilcox
 if (pValueWilcox_Thresold!=0)
 {
     clrs <- rev(Color_Ramp(30))
   breaks<-seq(0.001, 0.012, length.out = 10)
  breaks<-c(breaks,seq(0.0121,0.3,length.out = 10))
  breaks<-c(breaks,seq(0.31,1,length.out = 10))
   Function_HeatMap(pValueWilcox_Array,"Raw")
 }
    #HeatMap Averages 
    if(ABS_FC_Thresold!=0)
{
    clrs <- Color_Ramp(30)
  breaks<-seq(-10, -1.49, length.out = 10)
  breaks<-c(breaks,seq(-1.5,1.5,length.out = 10))
  breaks<-c(breaks,seq(1.51,10,length.out = 10))
  Function_HeatMap(Averages_Array,"Raw")
}
 setwd(Directory_Root)

    #endregion#





        #region#lightgreen


  for (Indice_Score in 1:Score_Q)        #**********************************************************START LOOP  Indice_Score Create Days averages of interresting days
  {
print(Indice_Score)
if(ABS_FC_Thresold!=0)
{
        print("Search Patterns Averages")
        Averages_Array_KeepBino[Indice_Score,]<-Averages_Array[Indice_Score,]
        temp<-Averages_Array[Indice_Score,]
        temp[(temp> -ABS_FC_Thresold)&(temp< ABS_FC_Thresold)] <- NA
      Averages_Array[Indice_Score,]<-temp
      if((MinimalDaysSequence>=2)&(MinimalDaysSequence!="GRADIENT"))
      {  
        temp[temp<= -ABS_FC_Thresold]<- -1;temp[temp>= +ABS_FC_Thresold]<- +1
        temp<-rle(temp)
        temp<-rep(temp$lengths >= MinimalDaysSequence,times = temp$lengths)
        Averages_Array_KeepBino[Indice_Score,][!temp]<-NA
        Averages_Array[Indice_Score,]<-Averages_Array_KeepBino[Indice_Score,]
      }
 print("End of Search Patterns Averages")
  }


   if (pValue_Thresold!=0){
        print("Search Patterns pValues Normal")
    
       
        pValue_Array_KeepBino[Indice_Score,]<-  pValue_Array[Indice_Score,]
        temp<-pValue_Array[Indice_Score,]
        temp[(temp> pValue_Thresold)] <- NA
      pValue_Array[Indice_Score,]<-temp
      if(MinimalDaysSequence>=2)
      {  
        temp[temp<= pValue_Thresold]<- +1
        temp<-rle(temp)
        temp<-rep(temp$lengths >= MinimalDaysSequence,times = temp$lengths)
        pValue_Array_KeepBino[Indice_Score,][!temp]<-NA
      } 
 pValue_Array[Indice_Score,]<-pValue_Array_KeepBino[Indice_Score,]
 print("End of Search Patterns pValue Normal")
   }


if (pValueWilcox_Thresold!=0)
{

        print("Search Patterns pValues Wilcox")
        pValueWilcox_Array_KeepBino[Indice_Score,]<-  pValueWilcox_Array[Indice_Score,]
        temp<-pValueWilcox_Array[Indice_Score,]
        temp[(temp> pValueWilcox_Thresold)] <- NA
      pValueWilcox_Array[Indice_Score,]<-temp
      if(MinimalDaysSequence>=2)
      {  
        temp[temp<= pValueWilcox_Thresold]<- +1
        temp<-rle(temp)
        temp<-rep(temp$lengths >= MinimalDaysSequence,times = temp$lengths)
        pValueWilcox_Array_KeepBino[Indice_Score,][!temp]<-NA
      } 
 pValueWilcox_Array[Indice_Score,]<-pValueWilcox_Array_KeepBino[Indice_Score,]
 print("End of Search Patterns pValue Wilcox")
}
        }    #**********************************************************End LOOP  Indice_Score      PATTERN
}           #**********************************************************  END LOOP IDENTIFY EPILEPSY BIAS          
    #endregion#
print("Debug")
  #region#blue

  #Print les heatmaps SELECTED FINALS
  dir.create("R_HeatMaps")
  setwd(paste(Directory_Root,"/R_HeatMaps",sep=""))

   row.names(pValue_Array)<-levels_factors
  row.names(pValueWilcox_Array)<-levels_factors
  row.names(Averages_Array)<-levels_factors
  colnames(pValue_Array)<-1:Days_Q
  colnames(pValueWilcox_Array)<-1:Days_Q
  colnames(Averages_Array)<-1:Days_Q

     #Heatmaps pValues
     
   if (pValue_Thresold!=0){
   clrs <- rev(Color_Ramp(30))
  breaks<-seq(0.0001, 0.01, length.out = 10)
  breaks<-c(breaks,seq(0.011,0.2,length.out = 10))
  breaks<-c(breaks,seq(0.21,0.4,length.out = 10))
   Function_HeatMap(pValue_Array,paste("p",pValue_Thresold,"_MinimalDaysSerie=",MinimalDaysSequence,sep=""))
   }
#Heatmaps pValuesWilcox
 if (pValueWilcox_Thresold!=0)
 {
     clrs <- rev(Color_Ramp(30))
   breaks<-seq(0.001, 0.012, length.out = 10)
  breaks<-c(breaks,seq(0.0121,0.3,length.out = 10))
  breaks<-c(breaks,seq(0.31,1,length.out = 10))
   Function_HeatMap(pValueWilcox_Array,paste("p",pValueWilcox_Thresold,"_MinimalDaysSerie=",MinimalDaysSequence,sep=""))
 }
    #HeatMap Averages 
    if(ABS_FC_Thresold!=0)
{
    clrs <- Color_Ramp(30)
  breaks<-seq(-10, -1.49, length.out = 10)
  breaks<-c(breaks,seq(-1.5,1.5,length.out = 10))
  breaks<-c(breaks,seq(1.51,10,length.out = 10))
  Function_HeatMap(Averages_Array,paste("|FC|≥",ABS_FC_Thresold,"_MinimalDaysSerie=",MinimalDaysSequence,sep=""))
}
 setwd(Directory_Root)

    #endregion#
  


  #region#lightgreen

    if (Debug_B)
    {
  dir.create("R_Tables")
  setwd(paste(Directory_Root,"/R_Tables",sep=""))
    
  
  pValue_Array<-rbind(colnames(pValue_Array),pValue_Array)
  row.names(pValue_Array)[1]<-"DATE"
  pValue_Array<-cbind(row.names(pValue_Array),pValue_Array)
write.table(pValue_Array,"pValue_Array.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
  
  
  pValueWilcox_Array<-rbind(colnames(pValueWilcox_Array),pValueWilcox_Array)
  row.names(pValueWilcox_Array)[1]<-"DATE"
  pValueWilcox_Array<-cbind(row.names(pValueWilcox_Array),pValueWilcox_Array)
 write.table(pValueWilcox_Array,"pValueWilcox_Array.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")

  
  Averages_Array<-rbind(colnames( Averages_Array),Averages_Array)
  row.names(Averages_Array)[1]<-"DATE"
  Averages_Array<-cbind(row.names(Averages_Array),Averages_Array)
write.table(Averages_Array,"Averages_Array.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
 
pValue_Array<-pValue_Array[-1,-1]
 Averages_Array<-Averages_Array[-1,-1]
  pValueWilcox_Array<-pValueWilcox_Array[-1,-1]
  
   setwd(Directory_Root)
  print("End Export Tables")
    }



#endregion#


#if(!IdentifyEpilepsyBias)
if(FALSE)  # the script is now to oriented to identify epilepsy bias
{
  
  #region#black   "timeWindow" 
  Input_L_Raw[, 3] <- as.numeric(Input_L_Raw[, 3])
  Input_L_Raw[, 4] <- as.numeric(Input_L_Raw[, 4])
  Input_L_Raw <- Input_L_Raw[order(Input_L_Raw[, 4]), ]
  Time_delta <- 1 + max(Input_L_Raw[, 4]) - min(Input_L_Raw[, 4])
  rownames(Input_L_Raw) <- seq(1:(dim(Input_L_Raw)[1]))
  Input_L_Raw <- cbind(Input_L_Raw, Input_L_Raw[, 4])
  temp_verre <- 0
  
  temp_k <- seq(1:Time_delta) %% (TimeWindow)
  temp_k <- c(1,temp_k)
  temp_k[length(temp_k)]<-0
  temp_k <- which(temp_k == 0)
  
  for (i in 1:(ceil(Time_delta/TimeWindow)))   #1:length(temp_K)
  {
    
    if(length(which(Input_L_Raw[, 5] < 10000000 ))<MinimumProfilLength){ Input_L_Raw[which(Input_L_Raw[, 5] < 10000000 ), 5]<-    10000000 + i ;  break}
    
    temp1 <- max(which(Input_L_Raw[, 5] < (temp_k[i])))
    if (abs(temp1)>length(Input_L_Raw[,5])) {
      temp1<-length(Input_L_Raw[,5])
    }
    
    Input_L_Raw[, 5][temp_verre:temp1] <- 10000000 + i
    temp_verre <- temp1 + 1
  }
  colnames(Input_L_Raw)[5] <- paste("Time_windows_", TimeWindow, "days", sep = "")
  Input_L_Raw[, 5] <- Input_L_Raw[, 5] - 10000000
  Input_L_Raw <- split(Input_L_Raw, Input_L_Raw[, 5])
  print("END TIMEWINDOW")
  #endregion#
  
  #region#black    Use function1 pour chaque "TimeWindow"
  for (h in 1:length(Input_L_Raw))
  {
    Inject_H <- Input_L_Raw[[h]][, -5]
    Profils_export_L[[h]] <- Function1(Inject_H, TimeBining, TimeShift, MinimumProfilLength, MinimumQuantityOfPatientsPerProfil, DateOrigine, Correl_Thresold,h)
    print(paste(h, "_", length(Input_L_Raw), sep = ""))
  }#endregion#
  
  
  print("Exporting profils")
  if (max(as.numeric(lapply(Profils_export_L,length))) == 0) {  stop("*********** CANCELLED No Profils To Export ***********") }
  
  for (i in 1:length(Profils_export_L)) {  Profils_export_Array <- bind_rows(Profils_export_Array, ldply(Profils_export_L[[i]], data.frame)) }
  
  
  
 
}


#region#green DataNormalization
Input_A_numerics_NotNorm<-Input_A_numerics
if(DataNormalization)
{   
  print("Normalization")
  
 
    if (Debug_B){write.table(Input_A,"R_InputArrayCorrected_NOT_Normalized.tabtxt",col.names=FALSE,row.names=FALSE,sep="\t")}

  for (indice_factor in 1:Score_Q)                       
  {
  #  print(paste(Factor_indice,"/",Score_Q))
    temp<-which(Input_A_header[,2]==Score_L[indice_factor])
     temp1<-Input_A_numerics[temp,]
     temp_sd <- sd(temp1, na.rm = TRUE) 
    temp_average <- mean(temp1, na.rm = TRUE) 
    Input_A_numerics[temp,] <- (temp1-temp_average )/temp_sd
    
  }
  Input_A[,-c(1:2)]<- Input_A_numerics

  if (Debug_B){write.table(Input_A,"R_InputArrayCorrectedNormalized.tabtxt",col.names=FALSE,row.names=FALSE,sep="\t")}
}
#endregion#



#region#yellow#########
if (PCA_Predictors&IdentifyEpilepsyBias)
{
  
  
  print("PCA_Predictors")

  temp<-rownames(Averages_Array)
  Averages_Array<-apply(Averages_Array,2,as.numeric)
  pValue_Array<-apply(pValue_Array,2,as.numeric)
  pValueWilcox_Array<-apply(pValueWilcox_Array,2,as.numeric)
  rownames(Averages_Array)<-temp
  rownames(pValue_Array)<-temp
  rownames(pValueWilcox_Array)<-temp
  
  Input_ForPCA_averages<-1:Patients_Q
  Input_ForPCA_pValues<-1:Patients_Q
  Input_ForPCA_pValuesWilcox<-1:Patients_Q
  Input_Logic<-1:Patients_Q
  

temp2<-vis_miss(as.data.frame(Input_A_numerics),warn_large_data = FALSE)
if (Debug_B)
{
  png("CompletionOfData.png", width=PngX, height=PngY, units="px")
plot(temp2)
dev.off()
}
   #endregion#
  

#region#blue

  
  for (Indice_Score in 1:Score_Q)
  {
    print(paste("Creating potential predictors from",Score_L[Indice_Score],", Score",Indice_Score,"on",Score_Q))
    
    temp <- which(Input_A_header[,2] == Score_L[Indice_Score])
    temp_Score<- which(rownames(Averages_Array) == Score_L[Indice_Score])

    temp1<-Averages_Array[Indice_Score,]<1
    temp2<-Averages_Array[Indice_Score,]>1
temp3<-rep(NA,Days_Q)
temp3[temp1]<- -1 ; temp3[temp2]<- +1 
temp1<-rle(temp3)
temp3<-cumsum(temp1$lengths)
temp_end<-temp3[which(!is.na(temp1$values))]
temp1$lengths[which(!is.na(temp1$value))]
temp_start<-temp_end - temp1$lengths[which(!is.na(temp1$value))]+1
temp_ToAverage<-cbind(temp_start,temp_end)
if (nrow(temp_ToAverage)>=1)
{
for(indice_row in 1:nrow(temp_ToAverage))
{
 if(temp_ToAverage[indice_row,1]!=temp_ToAverage[indice_row,2])
 {
 temp4<-rowMeans  (Input_A_numerics[temp,temp_ToAverage[indice_row,1]:temp_ToAverage[indice_row,2]])
 Input_ForPCA_averages<-cbind( Input_ForPCA_averages,temp4)
colnames(Input_ForPCA_averages)[ncol(Input_ForPCA_averages)]<-paste("Mean_",Score_L[Indice_Score],"_Day",temp_ToAverage[indice_row,1],"_To_",temp_ToAverage[indice_row,2],sep="")
}else{
  temp4<-  Input_A_numerics[temp,temp_ToAverage[indice_row,1]]
 Input_ForPCA_averages<-cbind( Input_ForPCA_averages,temp4)
colnames(Input_ForPCA_averages)[ncol(Input_ForPCA_averages)]<-paste("Mean_",Score_L[Indice_Score],"_Day",temp_ToAverage[indice_row,1],sep="")
}
}
}

  temp1<-pValue_Array[Indice_Score,]>0
temp3<-rep(NA,Days_Q)
temp3[temp1]<- 1 
temp1<-rle(temp3)
temp3<-cumsum(temp1$lengths)
temp_end<-temp3[which(!is.na(temp1$values))]
temp1$lengths[which(!is.na(temp1$value))]
temp_start<-temp_end - temp1$lengths[which(!is.na(temp1$value))]+1
temp_ToAverage<-cbind(temp_start,temp_end)
if (nrow(temp_ToAverage)>=1)
{
for(indice_row in 1:nrow(temp_ToAverage))
{
 if(temp_ToAverage[indice_row,1]!=temp_ToAverage[indice_row,2])
 {
 temp4<-rowMeans  (Input_A_numerics[temp,temp_ToAverage[indice_row,1]:temp_ToAverage[indice_row,2]])
 Input_ForPCA_pValues <-cbind( Input_ForPCA_pValues,temp4)
colnames(Input_ForPCA_pValues)[ncol(Input_ForPCA_pValues)]<-paste("Mean_",Score_L[Indice_Score],"_Day",temp_ToAverage[indice_row,1],"_To_",temp_ToAverage[indice_row,2],sep="")
}else{
   temp4<-  Input_A_numerics[temp,temp_ToAverage[indice_row,1]]
 Input_ForPCA_pValues<-cbind( Input_ForPCA_pValues,temp4)
colnames(Input_ForPCA_pValues)[ncol(Input_ForPCA_pValues)]<-paste("Mean_",Score_L[Indice_Score],"_Day",temp_ToAverage[indice_row,1],sep="")
}
}
}
  temp1<-pValueWilcox_Array[Indice_Score,]>0
temp3<-rep(NA,Days_Q)
temp3[temp1]<- 1 
temp1<-rle(temp3)
temp3<-cumsum(temp1$lengths)
temp_end<-temp3[which(!is.na(temp1$values))]
temp1$lengths[which(!is.na(temp1$value))]
temp_start<-temp_end - temp1$lengths[which(!is.na(temp1$value))]+1
temp_ToAverage<-cbind(temp_start,temp_end)
if (nrow(temp_ToAverage)>=1)
{
for(indice_row in 1:nrow(temp_ToAverage))
{
 if(temp_ToAverage[indice_row,1]!=temp_ToAverage[indice_row,2])
 {
 temp4<-rowMeans  (Input_A_numerics[temp,temp_ToAverage[indice_row,1]:temp_ToAverage[indice_row,2]])
 Input_ForPCA_pValuesWilcox <-cbind( Input_ForPCA_pValuesWilcox,temp4)
colnames(Input_ForPCA_pValuesWilcox)[ncol(Input_ForPCA_pValuesWilcox)]<-paste("Mean_",Score_L[Indice_Score],"_Day",temp_ToAverage[indice_row,1],"_To_",temp_ToAverage[indice_row,2],sep="")
}else{
   temp4<-  Input_A_numerics[temp,temp_ToAverage[indice_row,1]]
 Input_ForPCA_pValuesWilcox<-cbind( Input_ForPCA_pValuesWilcox,temp4)
colnames(Input_ForPCA_pValuesWilcox)[ncol(Input_ForPCA_pValuesWilcox)]<-paste("Mean_",Score_L[Indice_Score],"_Day",temp_ToAverage[indice_row,1],sep="")
}
}
}




  }


   #endregion#
  #region#lightblue#########
  }

Flag_Temp<-FALSE
if(dim(cbind(Input_ForPCA_averages,0))[2]>=3){Flag_Temp<-TRUE;Input_Logic<-Input_ForPCA_averages;Input_Logic<-Input_Logic[,-1]}

if (Flag_Temp){Input_Logic<-cbind(Input_ForPCA_pValues,Input_Logic);Input_Logic<-Input_Logic[,-1]}
if (!Flag_Temp){if(dim(cbind(Input_ForPCA_pValues,0))[2]>=3){Flag_Temp<-TRUE;Input_Logic<-Input_ForPCA_pValues;Input_Logic<-Input_Logic[,-1]}}


if (Flag_Temp){Input_Logic<-cbind(Input_ForPCA_pValuesWilcox,Input_Logic);Input_Logic<-Input_Logic[,-1]}
if (!Flag_Temp){if(dim(cbind(Input_ForPCA_pValuesWilcox,0))[2]>=3){Flag_Temp<-TRUE;Input_Logic<-Input_ForPCA_pValuesWilcox;Input_Logic<-Input_Logic[,-1]}}


if(dim(cbind(Input_Logic,0))[2]<3){write.table(tag,"NOTHING_FOUND");stop("WARNING NOTHING FOUND")}
if (length(dim(Input_ForPCA_averages)[2]) !=0) {rownames(Input_ForPCA_averages)<-Patients_L} 
if (length(dim(Input_ForPCA_pValues)[2]) !=0) {rownames(Input_ForPCA_pValues)<-Patients_L}
if (length(dim(Input_ForPCA_pValuesWilcox)[2]) !=0) {rownames(Input_ForPCA_pValuesWilcox)<-Patients_L}
rownames(Input_Logic)<-Patients_L


Input_Logic<-Input_Logic[,order(colnames(Input_Logic))]
temp<-which(duplicated(colnames(Input_Logic)))

if(length(temp)!=0) {Input_Logic<-Input_Logic[,-temp]}
if (Debug_B)
{
 png("R_CompletionOfPotentialPredictors_ALL.png", width=PngX, height=PngY, units="px")
plot(vis_miss(as.data.frame(Input_Logic),warn_large_data = FALSE))
dev.off()
}

  if (Debug_B){write.table(Input_ForPCA_averages,"R_InputForPCA_averages.tabtxt",sep="\t")}
  if (Debug_B){write.table(Input_ForPCA_pValues,"R_InputForPCA_pValues.tabtxt",sep="\t")}
  if (Debug_B){write.table(Input_ForPCA_pValuesWilcox,"R_InputForPCA_pValuesWilcox.tabtxt",sep="\t")}
  if (Debug_B){write.table(Input_Logic,"R_InputForPCA_ALL.tabtxt",sep="\t")}
  #endregion#



   #region#pink#########

Input_Logic<-as.data.frame(Input_Logic)
Patients_EpilepsyQ<-length(Row_Epilepsy)
Patients_ControlQ<-length(Row_Control)
Patients_ToPredictQ<-length(Row_EpilepsyToPredict)

#Input_ForPCA_OnlyControl<-Input_Logic[Row_Control,]
#Input_ForPCA_OnlyEpileptic<-Input_Logic[Row_Epilepsy,]
temp<-which(apply(Input_Logic[Row_Epilepsy,],2,function(X){(sum(is.na(X)))<=(ceil(FractionMaxCreatedForLogicAnalyzis*Patients_EpilepsyQ))}))
Input_Logic<-Input_Logic[,temp]
#Input_ForPCA_OnlyControl<-Input_ForPCA_OnlyControl[,temp]
if ((Debug_B)&length(dim(Input_Logic))!=0)
{
png(paste("R_Completion90p+_Epilepsy_",length(temp),"Factors.png"), width=PngX, height=PngY, units="px")
plot(vis_miss(Input_Logic[Row_Epilepsy,]))
dev.off()
}

print("correcting the few missing factors among epilepsy data by group average of Epilepsy, also controls correction")
if ((length(dim(Input_Logic))!=0 )&( dim(Input_Logic)[2]>=MinimumQuantityVariablesAnalyzedByGLMNET))
{
Input_Logic[Row_Epilepsy,]<-as.data.frame(apply(Input_Logic[Row_Epilepsy,],2,function(X){X[which(is.na(X))]<-mean(X,na.rm=TRUE)   ;return (X)                     }))
Input_Logic[-Row_Epilepsy,]<-as.data.frame(apply(Input_Logic[-Row_Epilepsy,],2,function(X){X[which(is.na(X))]<-mean(X,na.rm=TRUE)   ;return (X)                     }))
} else {
    stop("NotEnoughVariablesForGLMNET")
}
Input_Logic<-cbind(NA,Input_Logic)

Input_Logic[Row_Epilepsy,1]<-1   #These are code for logistic glmnet
Input_Logic[Row_Control,1]<-0    #These are code for logistic glmnet
Input_Logic[Row_EpilepsyToPredict,1]<- 2  # new code for to predict is '2'

colnames(Input_Logic)[1]<-"EpileticStatus"

 if(Debug_B){   save.image("Before_GLMNET.rdata")}

#endregion#




#region#red
print("GLMNET")
if (length(Row_EpilepsyToPredict)!=0) {
Model_GLMNET<-glmnet(as.matrix(Input_Logic[-Row_EpilepsyToPredict,-1]), as.factor(Input_Logic[-Row_EpilepsyToPredict,1]),family = "binomial",alpha=alpha,pmax=VariablesNeeded)   # If stuck look in Newtown, Relax and path = TRUE
}
if (length(Row_EpilepsyToPredict)==0) {
Model_GLMNET<-glmnet(as.matrix(Input_Logic[,-1]), as.factor(Input_Logic[,1]),family = "binomial",alpha=alpha,pmax=VariablesNeeded)   # If stuck look in Newtown, Relax and path = TRUE
}



#endregion#




#region#pink

png(paste("R_GLMNET_",tag,".png"), width=PngX, height=PngY, units="px")  
plot(Model_GLMNET,label=TRUE,xvar="dev")
dev.off()

temp1<-predict(Model_GLMNET, as.matrix(Input_Logic[,-1]),type="class")  ##Clasement
temp1<-temp1[,ncol(temp1)]
temp1<-paste("Classe=(",temp1,")",sep="")
temp2<-as.matrix(predict(Model_GLMNET, as.matrix(Input_Logic[,-1]),type="response")) ##PROBA
temp2<-temp2[,ncol(temp2)]
temp3<-runif(length(temp2),min = 0,max=1)
png(paste("R_GLMNET_Class_",tag,".png"), width=PngX, height=PngY, units="px")  
temp_Colors<-rep(NA,Patients_Q)
temp_Colors[Row_Control]<-"blue"
temp_Colors[Row_Epilepsy]<-"red"
temp_Colors[Row_EpilepsyToPredict]<-"green"
plot( x=100*temp2, y=temp3,ylab="",xlab="Proba Epilepsy (%)",pch=19,bty="n",yaxt="n",col=temp_Colors,xlim=c(0,100),main=paste("Classification_Ep",length(Row_Epilepsy),"_Ctrl",length(Row_Control),"_VarMax",VariablesNeeded))
addTextLabels(Patients_L, x=100*temp2, y=temp3,cex.label=1, col.label=temp_Colors)
dev.off()
temp2<-round(100*temp2,0) 
temp2<-paste("P(1)=",temp2,"%",sep="")
temp<-cbind(Patients_L,paste(temp1,temp2))
write.table(file="Predicteurs_Patients_GLMNET.tabtxt",temp,sep="\t")
temp<-as.matrix(predict(Model_GLMNET, type="coefficient",s=0))
write.table(file="Predicteurs_Variables_GLMNET.tabtxt",temp,sep="\t")
Boxplot_predictors_coeffs<-temp
temp<-which(temp[-1]!=0)

Boxplot_predictors_coeffs<-Boxplot_predictors_coeffs[-1][temp]

Boxplot_predictors<-Input_Logic[,c(1,1+temp)]

temp1<-Input_Logic[,c(1,1+temp)]
temp1[,1]<-as.factor(temp1[,1])
temp1<-PCA(temp1,quali.sup =1,graph=FALSE)  #Qualitsup!!!!
PCA_To_File_F(temp1,paste("PCA on best",VariablesNeeded,"predictors"))

Boxplot_predictors<-Boxplot_predictors[-(which(Boxplot_predictors[,1]==2)),]
Boxplot_predictors_ep<-which(Boxplot_predictors[,1]==1)
Boxplot_predictors_ctrl<-which(Boxplot_predictors[,1]==0)
Boxplot_predictors<-Boxplot_predictors[,-1]
for (indice_predictors in 1:ncol(Boxplot_predictors))
{
png(paste("Violon_",colnames(Boxplot_predictors)[indice_predictors],".png",sep=""), width=PngX, height=PngY, units="px")  
vioplot(Boxplot_predictors[Boxplot_predictors_ctrl,indice_predictors],Boxplot_predictors[Boxplot_predictors_ep,indice_predictors], names=c("Control", "Epilepsy"),    col=c("blue","red"),main =paste("Means_",colnames(Boxplot_predictors)[indice_predictors],"coeff=",round(Boxplot_predictors_coeffs[indice_predictors],digits = 3)),areaEqual =FALSE)

dev.off()


png(paste("Boxplot_",colnames(Boxplot_predictors)[indice_predictors],".png",sep=""), width=PngX, height=PngY, units="px")  
boxplot(Boxplot_predictors[Boxplot_predictors_ctrl,indice_predictors],Boxplot_predictors[Boxplot_predictors_ep,indice_predictors], names=c("Control", "Epilepsy"),col=c("blue","red"),main =paste("Means_",colnames(Boxplot_predictors)[indice_predictors],"coeff=",round(Boxplot_predictors_coeffs[indice_predictors],digits = 2)))

dev.off()


temp<-colnames(Boxplot_predictors)[indice_predictors]
temp<-gsub(pattern="Mean_",replacement="",colnames(Boxplot_predictors)[indice_predictors])
temp_factor<-sub("_Day.*",replacement="", temp)
temp_start<-sub(".*Day",replacement="", temp)
temp_start<-as.numeric(sub("_.*",replacement="", temp_start))
temp_end<-as.numeric(sub(".*To_",replacement="", temp)); if (is.na(temp_end)) {temp_end<-temp_start}


temp<-Input_A_numerics_NotNorm[which(Input_A_header[,2]==temp_factor),]
temp_ctrl<-temp[Row_Control,temp_start:temp_end] %>% as.vector() %>% na.omit()
temp_ep<-temp[Row_Epilepsy,temp_start:temp_end] %>% as.vector() %>% na.omit()
temp_ctrl_x<-runif(length(temp_ctrl),min = 0.8,max=1.2)
temp_ep_x<-runif(length(temp_ep),min = 1.8,max=2.2)


temp_ctrl<-temp_ctrl+runif (length(temp_ctrl),min=-(max(temp_ctrl)-min(temp_ctrl))/40,max= (max(temp_ctrl)-min(temp_ctrl))/40)    #5% pepper

temp_ep<-temp_ep+runif (length(temp_ep),min=-(max(temp_ep)-min(temp_ep))/40,max= (max(temp_ep)-min(temp_ep))/40)    #5% pepper







#EN COURS************************
#plot( x=100*temp2, y=temp3,ylab="",xlab="Proba Epilepsy (%)",pch=19,bty="n",yaxt="n",col=temp_Colors,xlim=c(0,100),main=paste("Classification_Ep",length(Row_Epilepsy),"_Ctrl",length(Row_Control),"_VarMax",VariablesNeeded))

png(paste("Scaterplot_",temp_factor,".png",sep=""), width=PngX, height=PngY, units="px")  
plot(x=c(temp_ctrl_x,temp_ep_x),y=c(temp_ctrl,temp_ep),col=c(rep("blue",length(temp_ctrl)),rep("red",length(temp_ep))),main=paste(temp_factor,"Days",temp_start,"to",temp_end,"coeff=",round(Boxplot_predictors_coeffs[indice_predictors],digits = 2)),xlab="Control(Blue) Vs Epilepsy(Red)",ylab="Measurement (units)",xaxt="n")
segments(c(0.8,1.8),c(median(temp_ctrl),median(temp_ep)),x1=c(1.2,2.2),y1=c(median(temp_ctrl),median(temp_ep)))
segments(c(0.8,1.8),c(mean(temp_ctrl),mean(temp_ep)),x1=c(1.2,2.2),y1=c(mean(temp_ctrl),mean(temp_ep)))
text(1.3,mean(temp_ctrl),"Ave",col="blue")
text(1.3,median(temp_ctrl),"Med",col="blue")
text(1.7,mean(temp_ep),"Ave",pos =4,col="red")
text(1.7,median(temp_ep),"Med",pos=4,col="red")

dev.off()
}

#endregion#




print("*********** END ******************")


